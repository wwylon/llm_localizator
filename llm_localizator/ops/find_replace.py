"""``find-replace``: literal find and replace over one locale's translations (C-020).

Previews every changed key with its before and after text. Without ``confirm`` nothing is
written. Applying needs ``keys`` (``namespace.key``), so the person ticks what to change.
Each result is checked by the normal validator, verified and locked keys are skipped, and
writes are stamped as human edits with ``trigger=find-replace`` (ADR-19, ADR-48).
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import is_locked, is_verified
from ..core.standards import get_standard
from ..core.validate import check_max_chars, validate_translation
from ..pipeline.recording import provenance_stores, record_candidate
from ..projects import ContextNotes, GlossaryCache, ProjectConfig
from .types import FindReplaceRequest, OpResult

__all__ = ["op_find_replace"]

MAX_ROWS = 500


def _fail(summary: str) -> OpResult:
    return OpResult(ok=False, exit_code=64, command="find-replace", summary=summary, lines=[summary])


def _replace(text: str, find: str, repl: str, case_sensitive: bool) -> str:
    if case_sensitive:
        return text.replace(find, repl)
    low, out, i = text.lower(), [], 0
    needle = find.lower()
    while True:
        j = low.find(needle, i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:j])
        out.append(repl)
        i = j + len(find)


def op_find_replace(cfg: ProjectConfig, req: FindReplaceRequest) -> OpResult:
    locale = req.locale
    if not req.find:
        return _fail("find-replace needs text to find")
    if not locale or locale not in cfg.targets:
        return _fail(f"unknown target locale {locale!r}")
    if cfg.is_frozen(locale):
        return _fail(f"{locale} is frozen")
    catalog = catalog_for(cfg)
    stores = provenance_stores(cfg)
    notes = ContextNotes(cfg.context_dir)
    glossary_cache = GlossaryCache(
        cfg.glossary_path, shared=list(getattr(cfg, "glossary_shared", []) or []),
        conflict=getattr(cfg, "glossary_conflict", "own"),
    )
    standard = get_standard(getattr(cfg, "catalog_standard", None))
    rows: list[dict] = []
    for ns in cfg.namespaces_for(catalog):
        if req.namespace and ns != req.namespace:
            continue
        source_map = catalog.load(cfg.source_locale, ns)
        target = catalog.load(locale, ns)
        for key, current in target.items():
            src = source_map.get(key)
            if not isinstance(current, str) or not isinstance(src, str):
                continue
            after = _replace(current, req.find, req.replace, req.case_sensitive)
            if after == current:
                continue
            row = {"namespace": ns, "key": key, "before": current, "after": after, "skip": None}
            entry = stores.state.entry(locale, ns, key)
            if is_locked(entry):
                row["skip"] = "locked"
            elif is_verified(entry):
                row["skip"] = "verified"
            else:
                ok, reason = validate_translation(
                    src, after, locale, glossary_cache.get(cfg.glossary_domains_for(ns)),
                    check_html=True if notes.html(ns, key) else None, standard=standard,
                )
                if not ok:
                    row["skip"] = f"fails validation: {reason}"
                elif check_max_chars(after, notes.max_chars(ns, key)):
                    row["skip"] = "over maxChars"
            rows.append(row)
    rows.sort(key=lambda r: (r["namespace"], r["key"]))
    total = len(rows)
    rows = rows[:MAX_ROWS]

    chosen = set(req.keys or [])
    todo = [r for r in rows if r["skip"] is None and f"{r['namespace']}.{r['key']}" in chosen]
    apply = bool(req.confirm and not req.dry_run and todo)
    written: list[str] = []
    if apply:
        with project_mutation_lock(cfg):
            pending: list = []
            by_ns: dict[str, dict[str, str]] = {}
            for r in todo:
                by_ns.setdefault(r["namespace"], {})[r["key"]] = r["after"]
            for ns, updates in by_ns.items():
                source_map = catalog.load(cfg.source_locale, ns)
                target = catalog.load(locale, ns)
                catalog.write(locale, ns, updates, source=source_map)
            for r in todo:
                ns, key = r["namespace"], r["key"]
                record_candidate(
                    state=stores.state, scores=stores.scores, history=stores.history,
                    locale=locale, namespace=ns, key=key,
                    source=catalog.load(cfg.source_locale, ns)[key],
                    previous=r["before"], text=r["after"], model="human", quality_score=1.0,
                    quality_signals=[f"find-replace {req.find!r}"], trigger="find-replace",
                    status="human", provider="human", pending_history=pending,
                    record_score=False,
                )
                written.append(f"{ns}.{key}")
            for loc, event in pending:
                stores.history.append(loc, event)
            stores.state.save_all([locale])
    lines = [
        f"{r['namespace']}.{r['key']}: {r['before']} -> {r['after']}"
        + (f"  [skipped: {r['skip']}]" if r["skip"] else "")
        for r in rows
    ]
    if apply:
        summary = f"changed {len(written)} key(s)"
    else:
        ready = sum(1 for r in rows if r["skip"] is None)
        summary = f"{total} key(s) match, {ready} can change (name them in keys and confirm to apply)"
    return OpResult(
        ok=True, exit_code=0, command="find-replace", summary=summary, lines=lines,
        data={"rows": rows, "written": written, "applied": apply, "total": total},
    )
