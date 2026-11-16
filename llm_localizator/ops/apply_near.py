"""``apply-near``: copy one human edit onto similar keys the person picks (C-010).

Identical source texts are already filled by the editor's save (``propagate_identical``).
This op covers *near* source texts: it lists keys whose English is at least
``min_similarity`` like the edited key's (character edit similarity, the CAT-tool fuzzy
match), and writes the edited translation onto the ones named in ``keys``. Without
``confirm`` it only previews. Each write is checked by the normal validator for that
key, skips verified, locked, human-edited and intentional keys, and is stamped as a
human edit with ``trigger=apply-near`` and ``propagated_from`` so history shows where
the text came from (ADR-19, ADR-48).
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.history import make_history_event
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import is_locked, is_verified, src_hash
from ..catalog.tm import edit_similarity
from ..core.standards import get_standard
from ..core.validate import check_max_chars, validate_translation
from ..pipeline.recording import provenance_stores, record_candidate
from ..projects import ContextNotes, GlossaryCache, ProjectConfig
from .types import ApplyNearRequest, OpResult

__all__ = ["op_apply_near"]

MAX_CANDIDATES = 200


def _fail(summary: str, code: int = 64) -> OpResult:
    return OpResult(ok=False, exit_code=code, command="apply-near", summary=summary, lines=[summary])


def _blocked(entry: dict | None) -> str | None:
    if is_locked(entry):
        return "locked"
    if is_verified(entry):
        return "verified"
    status = (entry or {}).get("status")
    if status in ("human", "intentional"):
        return str(status)
    return None


def op_apply_near(cfg: ProjectConfig, req: ApplyNearRequest) -> OpResult:
    locale, ns, key = req.locale, req.namespace, req.key
    if not (locale and ns and key):
        return _fail("apply-near needs locale, namespace and key")
    if locale not in cfg.targets:
        return _fail(f"unknown target locale {locale!r}")
    if cfg.is_frozen(locale):
        return _fail(f"{locale} is frozen")
    catalog = catalog_for(cfg)
    origin_source = catalog.load(cfg.source_locale, ns).get(key)
    text = catalog.load(locale, ns).get(key)
    if not isinstance(origin_source, str) or not isinstance(text, str) or not text.strip():
        return _fail(f"{ns}.{key} needs a source text and a translation")
    if text == origin_source:
        return _fail(f"{ns}.{key} is still the source text; edit it first")

    stores = provenance_stores(cfg)
    notes = ContextNotes(cfg.context_dir)
    glossary_cache = GlossaryCache(
        cfg.glossary_path, shared=list(getattr(cfg, "glossary_shared", []) or []),
        conflict=getattr(cfg, "glossary_conflict", "own"),
    )
    standard = get_standard(getattr(cfg, "catalog_standard", None))
    threshold = req.min_similarity
    found: list[dict] = []
    for other_ns in cfg.namespaces_for(catalog):
        source_map = catalog.load(cfg.source_locale, other_ns)
        target = catalog.load(locale, other_ns)
        for other, src in source_map.items():
            if (other_ns, other) == (ns, key) or not isinstance(src, str) or not src.strip():
                continue
            if src == origin_source or cfg.is_skipped(other_ns, other, src):
                continue
            score = edit_similarity(origin_source, src)
            if score < threshold:
                continue
            current = target.get(other)
            entry = stores.state.entry(locale, other_ns, other)
            row = {
                "namespace": other_ns, "key": other, "source": src, "similarity": round(score, 3),
                "current": current if isinstance(current, str) else None, "skip": _blocked(entry),
            }
            if row["skip"] is None:
                ok, reason = validate_translation(
                    src, text, locale, glossary_cache.get(cfg.glossary_domains_for(other_ns)),
                    check_html=True if notes.html(other_ns, other) else None, standard=standard,
                )
                if not ok:
                    row["skip"] = f"fails validation: {reason}"
                elif check_max_chars(text, notes.max_chars(other_ns, other)):
                    row["skip"] = "over maxChars"
            found.append(row)
    found.sort(key=lambda r: (-r["similarity"], r["namespace"], r["key"]))
    found = found[:MAX_CANDIDATES]

    chosen = {k for k in (req.keys or [])}
    todo = [r for r in found if r["skip"] is None and f"{r['namespace']}.{r['key']}" in chosen]
    apply = bool(req.confirm and not req.dry_run and todo)
    written: list[str] = []
    if apply:
        with project_mutation_lock(cfg):
            pending: list = []
            by_ns: dict[str, dict[str, str]] = {}
            for r in todo:
                by_ns.setdefault(r["namespace"], {})[r["key"]] = text
            for other_ns, updates in by_ns.items():
                source_map = catalog.load(cfg.source_locale, other_ns)
                target = catalog.load(locale, other_ns)
                catalog.write(locale, other_ns, updates, source=source_map)
            for r in todo:
                other_ns, other = r["namespace"], r["key"]
                src = catalog.load(cfg.source_locale, other_ns)[other]
                record_candidate(
                    state=stores.state, scores=stores.scores, history=stores.history,
                    locale=locale, namespace=other_ns, key=other, source=src,
                    previous=r["current"], text=text, model="human", quality_score=1.0,
                    quality_signals=[f"copied from {ns}.{key}"], trigger="apply-near",
                    status="human", provider="human", pending_history=pending,
                    record_score=False,
                )
                written.append(f"{other_ns}.{other}")
            for loc, event in pending:
                stores.history.append(loc, event)
            stores.state.save_all([locale])
    lines = [
        f"{r['similarity']:.0%} {r['namespace']}.{r['key']}: {r['source']}"
        + (f"  [skipped: {r['skip']}]" if r["skip"] else "")
        for r in found
    ]
    if apply:
        summary = f"wrote {len(written)} key(s) from {ns}.{key}"
    else:
        ready = sum(1 for r in found if r["skip"] is None)
        summary = f"{len(found)} similar key(s), {ready} can take this text (name them in keys and confirm to apply)"
    return OpResult(
        ok=True, exit_code=0, command="apply-near", summary=summary, lines=lines,
        data={"candidates": found, "written": written, "applied": apply, "origin": f"{ns}.{key}"},
    )
