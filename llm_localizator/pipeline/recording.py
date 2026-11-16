"""Shared provenance recording for accepted translation candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..catalog import StateStore, make_entry
from ..catalog.history import HistoryEvent, HistoryStore, make_history_event
from ..catalog.provenance import normalize_provider
from ..catalog.scores import ScoreStore
from ..core.hash import src_hash

if TYPE_CHECKING:
    from ..projects import ProjectConfig

__all__ = ["ProvenanceStores", "provenance_stores", "record_candidate"]


@dataclass
class ProvenanceStores:
    """The coordinated sidecars written for an accepted candidate."""

    state: StateStore
    scores: ScoreStore
    history: HistoryStore


def provenance_stores(cfg: ProjectConfig) -> ProvenanceStores:
    """Build all provenance stores using the project's configured roots."""
    return ProvenanceStores(
        state=StateStore(cfg.state_root()),
        scores=ScoreStore(cfg.scores_root()),
        history=HistoryStore(cfg.history_root()),
    )


def record_candidate(
    *,
    state: StateStore,
    scores: ScoreStore,
    history: HistoryStore,
    locale: str,
    namespace: str,
    key: str,
    source: str,
    previous: str | None,
    text: str,
    model: str,
    quality_score: float,
    quality_signals: list[str],
    trigger: str,
    status: str = "machine",
    provider: str | None = None,
    dimensions: dict[str, float] | None = None,
    scorer: str | None = None,
    candidates: list[dict] | None = None,
    pending_history: list[tuple[str, HistoryEvent]] | None = None,
    record_score: bool = True,
    edited_by: str | None = None,
    edited_by_name: str | None = None,
    note: str | None = None,
    screen: str | None = None,
    max_chars: int | None = None,
) -> dict:
    """Record one accepted candidate consistently across all sidecars.

    When *pending_history* is provided, history events are queued for a later
    flush alongside catalogue/state/scores (ADR-24). Otherwise they append
    immediately (web save / import under the mutation lock).
    """
    channel = normalize_provider(provider)
    entry = make_entry(
        source, model, status, provider=channel,
        note=note, screen=screen, max_chars=max_chars, target_value=text,
    )
    prev_entry = state.entry(locale, namespace, key)
    if (
        previous is not None
        and previous.strip() == text.strip()
        and prev_entry
        and prev_entry.get("verified_at")
    ):
        entry["verified_at"] = prev_entry["verified_at"]
        entry["verified_by"] = prev_entry.get("verified_by")
    if prev_entry and prev_entry.get("locked") is True:
        entry["locked"] = True
    # ``intentional`` (keep source as-is) survives a machine overwrite while the
    # source is unchanged; a source change re-opens the key.
    if (
        status == "machine"
        and prev_entry
        and prev_entry.get("status") == "intentional"
        and prev_entry.get("src_sha") == entry["src_sha"]
    ):
        entry["status"] = "intentional"
    if record_score:
        scores.record(
            locale, namespace, key,
            score=quality_score, signals=quality_signals, text=text,
            dimensions=dimensions, scorer=scorer,
        )
    else:
        scores.forget(locale, namespace, key)
    old_src = prev_entry.get("src_text") if prev_entry else None
    changed_src = (
        old_src if isinstance(old_src, str) and old_src != source else None
    )
    event = make_history_event(
        prev_src=changed_src, next_src=source,
        namespace=namespace, key=key, prev=previous, next_text=text,
        model=model, status=entry["status"], src_sha=src_hash(source),
        trigger=trigger, quality_score=quality_score if record_score else None,
        provider=channel,
        candidates=candidates,
        edited_by=edited_by,
        edited_by_name=edited_by_name,
    )
    if pending_history is not None:
        pending_history.append((locale, event))
    else:
        history.append(locale, event)
    state.record(locale, namespace, key, entry)
    return entry
