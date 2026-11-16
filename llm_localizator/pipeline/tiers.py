"""Content tiers (ADR-52): how much human involvement a string needs.

``human`` keys are never machine-translated and go to the review queue.
``review`` keys are translated as usual and also get a review ticket.
``auto`` is the ordinary pipeline. A tier never changes a key's status (ADR-48).
"""

from __future__ import annotations

import hashlib

from ..catalog.review_queue import open_review_queue
from ..core.keyglob import key_glob_matches
from ..catalog.state import is_locked, is_verified, needs_translation
from ..projects import ProjectConfig
from ..projects.context import ContextNotes

__all__ = [
    "TIER_HUMAN", "TIER_REVIEW", "sampled", "ticket_held", "ticket_reviewed", "tier_for",
]

TIER_HUMAN = "human"
TIER_REVIEW = "review"
_AUTO = "auto"


def tier_for(cfg: ProjectConfig, notes: ContextNotes, namespace: str, key: str) -> str:
    """A per-key context tier wins, then the first matching ``[quality.tiers]`` glob."""
    try:
        explicit = notes.tier(namespace, key)
    except Exception:  # a broken context file yields no override; doctor reports it
        explicit = None
    if explicit:
        return explicit
    for pattern, tier in getattr(cfg, "quality_tiers", {}).items():
        if key_glob_matches(pattern, namespace, key):
            return tier
    if getattr(cfg, "places", None) and cfg.place_policy(namespace, key) == "review":
        return TIER_REVIEW  # ADR-104: translated, then ticketed for a human
    return _AUTO


def sampled(percent: int, locale: str, namespace: str, key: str) -> bool:
    """Stable spot-check: the same key is always in or out for a given percentage."""
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    digest = hashlib.sha1(f"{locale}\0{namespace}\0{key}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100 < percent


def _announce(cfg: ProjectConfig, batch: list[dict], reason: str) -> None:
    """``review.pending`` webhook: one event per run and reason, never per key."""
    from ..ops.notify import notify_project

    locales = sorted({row["locale"] for row in batch})
    notify_project(cfg, {"event": "review.pending", "reason": reason, "tickets": len(batch), "locales": locales})


def ticket_held(cfg: ProjectConfig, held: list, report) -> int:
    """Queue one ticket per held ``human``-tier key/locale; existing open tickets stay as they are."""
    queue = open_review_queue(cfg)
    batch: list[dict] = []
    for item in held:
        if queue.find_open(item.locale, item.namespace, item.key) is not None:
            continue
        batch.append({
            "locale": item.locale, "namespace": item.namespace, "key": item.key,
            "reason": "tier:human", "source": item.source,
            "current": item.current or None,
        })
    queue.enqueue_many(batch)
    created = len(batch)
    if created:
        report(f"    tier human: {created} key(s) held for a translator (review queue)")
        _announce(cfg, batch, "tier:human")
    return created


def ticket_reviewed(cfg: ProjectConfig, notes: ContextNotes, work: list, state, report) -> int:
    """Ticket ``review``-tier keys whose translation was written in this run."""
    queue = open_review_queue(cfg)
    batch: list[dict] = []
    percent = int(getattr(cfg, "review_sample_percent", 100))
    for item in work:
        if tier_for(cfg, notes, item.namespace, item.key) != TIER_REVIEW:
            continue
        if not sampled(percent, item.locale, item.namespace, item.key):
            continue
        entry = state.entry(item.locale, item.namespace, item.key)
        if not entry or needs_translation(item.source, entry) or is_locked(entry) or is_verified(entry):
            continue
        if queue.find_open(item.locale, item.namespace, item.key) is not None:
            continue
        batch.append({
            "locale": item.locale, "namespace": item.namespace, "key": item.key,
            "reason": "tier:review", "source": item.source,
        })
    queue.enqueue_many(batch)
    created = len(batch)
    if created:
        report(f"    tier review: {created} key(s) queued for human review")
        _announce(cfg, batch, "tier:review")
    return created
