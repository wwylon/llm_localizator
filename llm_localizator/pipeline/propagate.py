"""Copy one accepted translation onto empty identical-source siblings.

Web save only. Translate still calls the model (ADR-43).
"""

from __future__ import annotations

from ..catalog.history import HistoryEvent, make_history_event
from ..catalog.state import is_locked, is_verified, make_entry, src_hash
from ..core.standards import get_standard
from ..core.validate import check_max_chars, validate_translation
from ..projects.config import ProjectConfig
from ..projects.context import ContextNotes

__all__ = ["propagate_identical"]


def propagate_identical(
    cfg: ProjectConfig,
    catalog,
    state,
    notes: ContextNotes,
    glossary: dict,
    *,
    locale: str,
    namespace: str,
    key: str,
    source_text: str,
    text: str,
    model: str,
    status: str,
    provider: str | None,
    pending_history: list[tuple[str, HistoryEvent]],
    edited_by: str | None = None,
    edited_by_name: str | None = None,
) -> list[tuple[str, str]]:
    """Fill missing or still-source siblings. Returns ``(namespace, key)`` written.

    A sibling is skipped when it is locked, verified, intentional, already
    translated, frozen, or when the copy fails that key's own validation
    (placeholders, HTML, or ``maxChars``).
    """
    if cfg.is_frozen(locale):
        return []
    if not isinstance(text, str) or text == source_text:
        return []
    origin = f"{namespace}.{key}" if namespace else key
    standard = get_standard(getattr(cfg, "catalog_standard", None))
    written: list[tuple[str, str]] = []
    for ns in cfg.namespaces_for(catalog):
        source_map = catalog.load(cfg.source_locale, ns)
        target = catalog.load(locale, ns)
        updates: dict[str, str] = {}
        accepted: list[tuple[str, str | None]] = []
        for other, src in source_map.items():
            if ns == namespace and other == key:
                continue
            if src != source_text or cfg.is_skipped(ns, other):
                continue
            if not isinstance(src, str):
                continue
            current = target.get(other)
            if current is not None and current != src:
                continue
            entry = state.entry(locale, ns, other) if state is not None else None
            if is_locked(entry) or is_verified(entry):
                continue
            if entry and entry.get("status") == "intentional":
                continue
            ok, _reason = validate_translation(
                src, text, locale, glossary,
                check_html=True if notes.html(ns, other) else None,
                standard=standard,
            )
            if not ok:
                continue
            if check_max_chars(text, notes.max_chars(ns, other)):
                continue
            updates[other] = text
            accepted.append((other, current if isinstance(current, str) else None))
        if not updates or state is None:
            continue
        merged = catalog.merge_for_write(source_map, target, updates)
        catalog.save(locale, ns, merged)
        for other, previous in accepted:
            state.record(
                locale, ns, other,
                make_entry(source_map[other], model, status, provider=provider, target_value=text),
            )
            pending_history.append((locale, make_history_event(
                namespace=ns,
                key=other,
                prev=previous,
                next_text=text,
                model=model,
                status=status,
                src_sha=src_hash(source_map[other]),
                trigger="propagated",
                provider=provider,
                propagated_from=origin,
                edited_by=edited_by,
                edited_by_name=edited_by_name,
            )))
            written.append((ns, other))
    return written
