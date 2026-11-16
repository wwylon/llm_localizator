"""``source-diff`` and the ``minimal-edit`` draft job (C-041, ADR-100).

``source-diff`` is read-only: for one key it returns the old and new English source from the
source-change log (ADR-52), the current translation of the old source, and the new-side spans
flagged as needing translation. ``minimal_edit_draft`` is the opt-in model step behind
``draft create --mode minimal-edit``: it asks for the smallest edit of that translation and
keeps the result in the draft store (C-018), never in the catalogue.
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.drafts import DraftStore
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.source_diff import diff_spans, needs_translation
from ..catalog.source_history import SourceHistory
from ..core.cldr import language_name
from ..pipeline.minimal_edit import minimal_edit
from ..projects import ProjectConfig
from ..providers import ProviderError, provider_for_locale
from .translate import _cloud_block
from .types import OpResult, TranslateRequest

__all__ = ["op_source_diff", "minimal_edit_draft"]


def _fail(command: str, summary: str, code: int = 64) -> OpResult:
    return OpResult(ok=False, exit_code=code, command=command, summary=summary, lines=[summary])


def _context(cfg: ProjectConfig, locale: str, namespace: str, key: str):
    """``(row, translation, current_source)`` or an error string."""
    if not (namespace and key):
        return "needs a namespace and a key"
    if locale and locale not in cfg.targets:
        return f"unknown target locale {locale!r}"
    row = SourceHistory(cfg.state_root()).latest(namespace, key)
    catalog = catalog_for(cfg)
    current = catalog.load(cfg.source_locale, namespace).get(key)
    translation = ""
    if locale:
        value = catalog.load(locale, namespace).get(key)
        translation = value if isinstance(value, str) else ""
    return row, translation, current if isinstance(current, str) else ""


def op_source_diff(cfg: ProjectConfig, locale: str, namespace: str, key: str) -> OpResult:
    ctx = _context(cfg, locale, namespace, key)
    if isinstance(ctx, str):
        return _fail("source-diff", f"source-diff {ctx}")
    row, translation, current = ctx
    if not row:
        return OpResult(
            ok=True, exit_code=0, command="source-diff", summary="no recorded source change",
            lines=["no recorded source change for this key"],
            data={"changed": False, "oldSource": "", "newSource": current,
                  "translation": translation, "spans": [], "newSpans": []},
        )
    old, new = row.get("prev_src", ""), row.get("next_src", "")
    spans = diff_spans(old, new)
    marked = needs_translation(spans)
    lines = [f"old: {old}", f"new: {new}"]
    if translation:
        lines.append(f"{locale}: {translation}")
    lines += [f"needs translation: {s['text'].strip()}" for s in marked if s["changed"] and s["text"].strip()]
    return OpResult(
        ok=True, exit_code=0, command="source-diff",
        summary="source changed" + ("" if new == current else " (the log is behind the catalogue)"),
        lines=lines,
        data={"changed": True, "oldSource": old, "newSource": new, "currentSource": current,
              "translation": translation, "timestamp": row.get("timestamp", ""),
              "spans": spans, "newSpans": marked},
    )


def minimal_edit_draft(cfg: ProjectConfig, locale: str, namespace: str, key: str, by: str = "") -> OpResult:
    command = "draft"
    if not locale or locale not in cfg.targets:
        return _fail(command, f"unknown target locale {locale!r}")
    ctx = _context(cfg, locale, namespace, key)
    if isinstance(ctx, str):
        return _fail(command, f"minimal-edit {ctx}")
    row, translation, current = ctx
    if not row:
        return _fail(command, "minimal-edit needs a recorded source change for this key")
    if row.get("next_src") != current:
        return _fail(command, "the source changed again after the log entry; run sync first")
    if not translation.strip():
        return _fail(command, "minimal-edit needs an existing translation to edit")
    blocked = _cloud_block(cfg, TranslateRequest(
        locales=[locale], namespace=namespace, keys=[f"{namespace}.{key}"],
    ))
    if blocked is not None:
        blocked.command = command
        return blocked
    model = cfg.model_for(locale)
    lines: list[str] = []
    try:
        provider = provider_for_locale(cfg, locale, report=lines.append)
        text = minimal_edit(
            provider, model, old_source=row["prev_src"], new_source=current,
            old_translation=translation, language=language_name(locale), cfg=cfg, locale=locale,
        )
    except ProviderError as exc:
        return _fail(command, f"model unavailable: {exc}", 1)
    if not text:
        return _fail(command, "the model returned no usable text", 1)
    with project_mutation_lock(cfg):
        entry = DraftStore.for_project(cfg).put(
            locale, namespace, key, text=text, score=None, model=model, source=current, by=by or "",
        )
    from .draft import _row
    from ..pipeline.recording import provenance_stores

    prior = provenance_stores(cfg).state.entry(locale, namespace, key)
    human = isinstance(prior, dict) and prior.get("status") == "human"

    return OpResult(
        ok=True, exit_code=0, command=command, summary="minimal-edit draft stored, not applied",
        lines=[text], data={"drafts": [_row(entry, False)], "previous": translation, "humanEdited": human},
    )
