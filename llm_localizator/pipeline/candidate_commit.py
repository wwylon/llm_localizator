"""Shared candidate commit helpers for translate / improve / review.

Keeps provenance and history construction aligned so the three pipelines
do not drift on status / provider stamps. Catalogue writes stay with each
pipeline's pending/flush path (flush_changes semantics are frozen).
"""

from __future__ import annotations

from ..catalog.history import HistoryEvent, make_history_event
from ..catalog.state import make_entry, state_key


def build_state_entry(
    source: str,
    *,
    model: str,
    status: str,
    provider: str | None = None,
    target_value: str | None = None,
    note: str | None = None,
    screen: str | None = None,
    max_chars: int | None = None,
) -> dict:
    """Build a state record for a freshly accepted candidate."""
    return make_entry(
        source,
        model,
        status,
        provider=provider,
        target_value=target_value,
        note=note,
        screen=screen,
        max_chars=max_chars,
    )


def history_for_write(
    *,
    namespace: str,
    key: str,
    prev: str | None,
    next_text: str,
    model: str,
    status: str,
    src_sha: str,
    trigger: str,
    quality_score: float | None = None,
    provider: str | None = None,
) -> HistoryEvent:
    return make_history_event(
        namespace=namespace,
        key=key,
        prev=prev,
        next_text=next_text,
        model=model,
        status=status,
        src_sha=src_sha,
        trigger=trigger,
        quality_score=quality_score,
        provider=provider,
    )


def record_tm_if(
    tm,
    *,
    enabled: bool,
    locale: str,
    source: str,
    text: str,
    model: str,
    context: str = "",
    provider: str | None = None,
    quality_score: float | None = None,
) -> None:
    if not enabled or tm is None or not (text or "").strip():
        return
    tm.record(
        locale=locale,
        source=source,
        text=text,
        model=model,
        context=context,
        provider=provider,
        quality_score=quality_score,
        verified=False,
    )


def score_key(namespace: str, key: str) -> str:
    return state_key(namespace, key)
