"""HTTP helpers for the review-queue page. Tickets stay in ``.llm-review``."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..catalog.review_queue import (
    STATUS_DONE,
    STATUSES,
    ReviewQueue,
    open_review_queue,
    ReviewTicket,
    _SAFE_LOCALE,
)
from ..catalog.scores import ScoreStore
from ..projects import ProjectConfig


def _bad_locale(locale: object) -> dict[str, Any] | None:
    if not isinstance(locale, str) or not _SAFE_LOCALE.fullmatch(locale) or ".." in locale:
        return {"ok": False, "error": "invalid locale"}
    return None


def _queue(cfg: ProjectConfig) -> ReviewQueue:
    return open_review_queue(cfg)


def _apply_localize_request(cfg: ProjectConfig, ticket: ReviewTicket) -> None:
    """Closing a ``localize-request`` ticket applies the accepted scan result (ADR-55)."""
    from ..ops.scan_decide import apply_request_ticket

    apply_request_ticket(cfg, ticket)


def _scores(cfg: ProjectConfig, scores: ScoreStore | None = None) -> ScoreStore:
    return scores if scores is not None else ScoreStore(cfg.scores_root())


def _display_ids(queue: ReviewQueue, locale: str) -> dict[str, str]:
    """``RQ-001`` style ids derived from creation order; nothing extra is stored."""
    ordered = sorted(queue.list_tickets(locale), key=lambda t: t.created_at)  # stable: file order breaks ties
    return {t.id: f"RQ-{n:03d}" for n, t in enumerate(ordered, 1)}


def ticket_payload(
    cfg: ProjectConfig,
    ticket: ReviewTicket,
    display_ids: dict[str, str] | None = None,
    *,
    scores: ScoreStore | None = None,
) -> dict[str, Any]:
    row = asdict(ticket)
    score_row = _scores(cfg, scores).get(ticket.locale, ticket.namespace, ticket.key) or {}
    qs = score_row.get("quality_score")
    row["score"] = float(qs) if qs is not None else None
    row["scorer"] = score_row.get("scorer")
    row["signals"] = list(score_row.get("signals") or [])
    if display_ids is None:
        display_ids = _display_ids(_queue(cfg), ticket.locale)
    row["display_id"] = display_ids.get(ticket.id, "")
    row["type"] = ticket.reason
    row["comment_count"] = len(ticket.comments)
    return row


def review_counts(cfg: ProjectConfig, locales: list[str]) -> dict[str, Any]:
    """Tickets per status over ``locales``; ``active`` is what the nav badge shows."""
    queue = _queue(cfg)
    counts = {status: 0 for status in sorted(STATUSES)}
    for locale in locales:
        for ticket in queue.list_tickets(locale):
            counts[ticket.status] = counts.get(ticket.status, 0) + 1
    active = sum(n for st, n in counts.items() if st != STATUS_DONE)
    return {"ok": True, "counts": counts, "active": active}


def list_review_tickets(
    cfg: ProjectConfig,
    *,
    locale: str,
    status: str | None = None,
    namespace: str | None = None,
    key: str | None = None,
    scores: ScoreStore | None = None,
) -> dict[str, Any]:
    if locale and (bad := _bad_locale(locale)):
        return bad
    if status is not None and status not in STATUSES:
        return {"ok": False, "error": f"unknown status {status!r}"}
    queue = _queue(cfg)
    counts = {st: 0 for st in sorted(STATUSES)}
    for t in queue.list_tickets(locale):
        counts[t.status] = counts.get(t.status, 0) + 1
    tickets = queue.list_tickets(locale, status)
    if namespace is not None or key is not None:
        tickets = [
            t for t in tickets
            if (namespace is None or t.namespace == namespace)
            and (key is None or t.key == key)
        ]
    ids = _display_ids(queue, locale)
    # One ScoreStore for the whole list — each ticket_payload used to build a
    # fresh store and re-parse the locale scores file (seconds × N tickets).
    store = _scores(cfg, scores)
    return {
        "ok": True,
        "locale": locale,
        "counts": counts,
        "tickets": [
            ticket_payload(cfg, t, ids, scores=store)
            for t in reversed(sorted(tickets, key=lambda t: t.created_at))
        ],
    }


def create_review_ticket(
    cfg: ProjectConfig,
    *,
    locale: str,
    namespace: str,
    key: str,
    reason: str,
    assignee: str | None = None,
    description: str | None = None,
    author: str | None = None,
    title: str | None = None,
    scores: ScoreStore | None = None,
) -> dict[str, Any]:
    if locale and (bad := _bad_locale(locale)):
        return bad
    if not locale or not key:
        return {"ok": False, "error": "locale and key are required"}
    if not reason:
        return {"ok": False, "error": "reason is required"}
    desc = (description or "").strip()
    if desc and not (author or "").strip():
        return {"ok": False, "error": "author is required when description is set"}
    queue = _queue(cfg)
    ticket = queue.enqueue(
        locale=locale,
        namespace=namespace or "",
        key=key,
        reason=reason,
        assignee=assignee or None,
        opened_by=(author or "").strip() or None,
        title=(title or "").strip() or None,
    )
    if desc:
        queue.add_comment(locale, ticket.id, author.strip(), desc)
        refreshed = [
            t for t in queue.list_tickets(locale) if t.id == ticket.id
        ]
        ticket = refreshed[0] if refreshed else ticket
    return {"ok": True, "ticket": ticket_payload(cfg, ticket, scores=scores)}


def comment_on_ticket(
    cfg: ProjectConfig,
    *,
    locale: str,
    ticket_id: str,
    author: str,
    body: str,
    resolve: bool = False,
    scores: ScoreStore | None = None,
) -> dict[str, Any]:
    if locale and (bad := _bad_locale(locale)):
        return bad
    if not (author or "").strip():
        return {"ok": False, "error": "author is required"}
    if not (body or "").strip():
        return {"ok": False, "error": "body is required"}
    queue = _queue(cfg)
    if not queue.add_comment(locale, ticket_id, author.strip(), body.strip()):
        return {"ok": False, "error": "ticket not found"}
    if resolve:
        if not queue.set_status(locale, ticket_id, STATUS_DONE, actor=author.strip()):
            return {"ok": False, "error": "could not resolve ticket"}
    tickets = [t for t in queue.list_tickets(locale) if t.id == ticket_id]
    if not tickets:
        return {"ok": False, "error": "ticket not found"}
    if resolve:
        _apply_localize_request(cfg, tickets[0])
    return {"ok": True, "ticket": ticket_payload(cfg, tickets[0], scores=scores)}


def set_ticket_status(
    cfg: ProjectConfig,
    *,
    locale: str,
    ticket_id: str,
    status: str,
    assignee: str | None = None,
    actor: str | None = None,
    scores: ScoreStore | None = None,
) -> dict[str, Any]:
    if locale and (bad := _bad_locale(locale)):
        return bad
    if status not in STATUSES:
        return {"ok": False, "error": f"unknown status {status!r}"}
    queue = _queue(cfg)
    path = queue.path_for(locale)
    before = path.read_bytes() if path.exists() else b""
    if not queue.set_status(locale, ticket_id, status, assignee=assignee, actor=actor):
        after = path.read_bytes() if path.exists() else b""
        if after != before:
            return {"ok": False, "error": "status write failed"}
        return {"ok": False, "error": "ticket not found"}
    tickets = [t for t in queue.list_tickets(locale) if t.id == ticket_id]
    # Apply scan decisions only when the ticket is closed — starting or
    # assigning work must not mutate the catalogue (ADR-55).
    if status == STATUS_DONE:
        _apply_localize_request(cfg, tickets[0])
    return {"ok": True, "ticket": ticket_payload(cfg, tickets[0], scores=scores)}
