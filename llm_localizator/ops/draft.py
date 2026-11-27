"""``draft``: model suggestions that wait in a store until a person accepts them (C-018, ADR-91).

``create`` runs the Suggest pipeline for one key and keeps the result in the draft store; the
catalogue, state, history and TM are untouched. ``accept`` validates the draft and writes it as
a human edit with ``trigger=draft-accept`` (ADR-19, ADR-48); verified and locked keys, and drafts
whose source text has changed since, are refused; so is a human-edited translation (ADR-48)
unless ``confirm`` is set (R-009, ADR-103). ``reject`` drops the draft. ``list`` shows them.
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.drafts import DraftStore, draft_id
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import is_locked, is_verified
from ..core.standards import get_standard
from ..core.validate import check_max_chars, validate_translation
from ..pipeline.recording import provenance_stores, record_candidate
from ..projects import ContextNotes, ProjectConfig
from .source_diff import minimal_edit_draft
from .suggest import op_suggest
from .types import DraftRequest, OpResult, SuggestRequest

__all__ = ["op_draft"]

ACTIONS = ("list", "create", "accept", "reject")


def _fail(summary: str, code: int = 64) -> OpResult:
    return OpResult(ok=False, exit_code=code, command="draft", summary=summary, lines=[summary])


def _targets(req: DraftRequest) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for ref in req.keys or []:
        ns, _, key = ref.partition(".")
        if ns and key:
            out.append((ns, key))
    if req.namespace and req.key:
        out.append((req.namespace, req.key))
    return list(dict.fromkeys(out))


def _row(entry: dict, stale: bool) -> dict:
    return {
        "locale": entry["locale"], "namespace": entry["namespace"], "key": entry["key"],
        "text": entry.get("text", ""), "score": entry.get("score"), "model": entry.get("model", ""),
        "ts": entry.get("ts", ""), "by": entry.get("by", ""), "stale": stale,
    }


def op_draft(cfg: ProjectConfig, req: DraftRequest) -> OpResult:
    action = req.action or "list"
    if action not in ACTIONS:
        return _fail(f"unknown draft action {action!r}")
    locale = req.locale
    if action != "list" and (not locale or locale not in cfg.targets):
        return _fail(f"unknown target locale {locale!r}")
    store = DraftStore.for_project(cfg)
    catalog = catalog_for(cfg)

    if action == "list":
        rows = []
        for entry in sorted(store.items().values(), key=lambda e: (e["locale"], e["namespace"], e["key"])):
            if locale and entry["locale"] != locale:
                continue
            if req.namespace and entry["namespace"] != req.namespace:
                continue
            src = catalog.load(cfg.source_locale, entry["namespace"]).get(entry["key"])
            rows.append(_row(entry, src != entry.get("source")))
        lines = [
            f"{r['locale']} {r['namespace']}.{r['key']}: {r['text']}"
            + ("  [stale: the source changed]" if r["stale"] else "")
            for r in rows
        ]
        return OpResult(
            ok=True, exit_code=0, command="draft", summary=f"{len(rows)} draft(s) waiting",
            lines=lines, data={"drafts": rows},
        )

    targets = _targets(req)
    if not targets:
        return _fail(f"draft {action} needs a key (namespace and key, or keys)")

    if action == "create":
        if len(targets) > 1:
            return _fail("draft create takes one key at a time")
        ns, key = targets[0]
        if req.mode == "minimal-edit":
            return minimal_edit_draft(cfg, locale, ns, key, req.by)
        if req.mode:
            return _fail(f"unknown draft mode {req.mode!r}")
        res = op_suggest(cfg, SuggestRequest(locale=locale, namespace=ns, key=key))
        if not res.ok:
            res.command = "draft"
            return res
        source = catalog.load(cfg.source_locale, ns)[key]
        with project_mutation_lock(cfg):
            entry = store.put(
                locale, ns, key, text=res.data["text"], score=res.data.get("score"),
                model=res.data.get("model", ""), source=source, by=req.by or "",
            )
        return OpResult(
            ok=True, exit_code=0, command="draft", summary="draft stored, not applied",
            lines=[entry["text"]], data={"drafts": [_row(entry, False)]},
        )

    if action == "reject":
        with project_mutation_lock(cfg):
            gone = [f"{ns}.{key}" for ns, key in targets if store.discard(draft_id(locale, ns, key))]
        return OpResult(
            ok=True, exit_code=0, command="draft", summary=f"rejected {len(gone)} draft(s)",
            lines=gone, data={"rejected": gone},
        )

    return _accept(cfg, req, store, catalog, targets)


def _accept(cfg, req: DraftRequest, store: DraftStore, catalog, targets) -> OpResult:
    locale = req.locale
    if cfg.is_frozen(locale):
        return _fail(f"{locale} is frozen")
    stores = provenance_stores(cfg)
    notes = ContextNotes(cfg.context_dir)
    glossary_cache = cfg.glossary_cache()
    standard = get_standard(getattr(cfg, "catalog_standard", None))
    written: list[str] = []
    skipped: list[str] = []
    with project_mutation_lock(cfg):
        pending: list = []
        for ns, key in targets:
            ref = f"{ns}.{key}"
            did = draft_id(locale, ns, key)
            entry = store.get(did)
            if not entry:
                skipped.append(f"{ref}: no draft")
                continue
            source_map = catalog.load(cfg.source_locale, ns)
            src = source_map.get(key)
            if src != entry.get("source"):
                skipped.append(f"{ref}: the source changed since the draft was made")
                continue
            state_entry = stores.state.entry(locale, ns, key)
            if is_locked(state_entry):
                skipped.append(f"{ref}: locked")
                continue
            if is_verified(state_entry):
                skipped.append(f"{ref}: verified")
                continue
            if isinstance(state_entry, dict) and state_entry.get("status") == "human" and not req.confirm:
                skipped.append(f"{ref}: human-edited; pass confirm to overwrite")
                continue
            text = entry["text"]
            ok, reason = validate_translation(
                src, text, locale, glossary_cache.get(cfg.glossary_domains_for(ns)),
                check_html=True if notes.html(ns, key) else None, standard=standard,
            )
            if not ok:
                skipped.append(f"{ref}: fails validation: {reason}")
                continue
            if check_max_chars(text, notes.max_chars(ns, key)):
                skipped.append(f"{ref}: over maxChars")
                continue
            target = catalog.load(locale, ns)
            previous = target.get(key)
            catalog.write(locale, ns, {key: text}, source=source_map)
            record_candidate(
                state=stores.state, scores=stores.scores, history=stores.history,
                locale=locale, namespace=ns, key=key, source=src,
                previous=previous if isinstance(previous, str) else "", text=text,
                model="human", quality_score=1.0,
                quality_signals=[f"draft from {entry.get('model') or 'model'}"],
                trigger="draft-accept", status="human", provider="human",
                pending_history=pending, record_score=False,
            )
            store.discard(did)
            written.append(ref)
        for loc, event in pending:
            stores.history.append(loc, event)
        if written:
            stores.state.save_all([locale])
    return OpResult(
        ok=True, exit_code=0, command="draft",
        summary=f"accepted {len(written)} draft(s)" + (f", skipped {len(skipped)}" if skipped else ""),
        lines=[f"accepted {r}" for r in written] + [f"skipped {s}" for s in skipped],
        data={"written": written, "skipped": skipped},
    )
