"""Review queue for human attention (audit A3).

Stored under ``<data_root>/.llm-review/{locale}.jsonl`` (ADR-112) — owned tickets with status,
assignee, comments, and reason (e.g. needs_context).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .io import append_text_line, rewrite_text_locked
from .state import now_iso, state_key

import re

# Locale is a file-name component under the review dir; never a path.
_SAFE_LOCALE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

__all__ = [
    "open_review_queue",
    "ReviewTicket",
    "ReviewQueue",
    "STATUS_OPEN",
    "STATUS_IN_PROGRESS",
    "STATUS_DONE",
    "STATUS_BLOCKED",
    "STATUSES",
]

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_BLOCKED = "blocked"
STATUSES = frozenset({
    STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_BLOCKED,
})


@dataclass
class ReviewTicket:
    id: str
    locale: str
    namespace: str
    key: str
    reason: str
    status: str = STATUS_OPEN
    assignee: str | None = None
    comments: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    source: str | None = None
    current: str | None = None
    escalated_at: str | None = None
    opened_by: str = "system"
    title: str | None = None
    events: list[dict] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, raw: dict) -> ReviewTicket | None:
        try:
            return cls(
                id=str(raw["id"]),
                locale=str(raw["locale"]),
                namespace=str(raw.get("namespace") or ""),
                key=str(raw["key"]),
                reason=str(raw.get("reason") or ""),
                status=str(raw.get("status") or STATUS_OPEN),
                assignee=raw.get("assignee"),
                comments=list(raw.get("comments") or []),
                created_at=str(raw.get("created_at") or ""),
                updated_at=str(raw.get("updated_at") or ""),
                source=raw.get("source"),
                current=raw.get("current"),
                escalated_at=raw.get("escalated_at"),
                opened_by=str(raw.get("opened_by") or "system"),
                title=raw.get("title"),
                events=list(raw.get("events") or []),
            )
        except (KeyError, TypeError, ValueError):
            return None


class ReviewQueue:
    """Append-friendly per-locale JSONL review tickets."""

    def __init__(self, directory: Path, ownership: dict[str, str] | None = None) -> None:
        self.dir = Path(directory)
        self.ownership = dict(ownership or {})
        self._cache: dict[str, list[ReviewTicket]] = {}
        self._stamp: dict[str, tuple[int, int]] = {}

    def _disk_stamp(self, locale: str) -> tuple[int, int]:
        try:
            st = self.path_for(locale).stat()
        except OSError:
            return (0, 0)
        return (st.st_mtime_ns, st.st_size)

    def path_for(self, locale: str) -> Path:
        if not isinstance(locale, str) or not _SAFE_LOCALE.fullmatch(locale) or ".." in locale:
            raise ValueError(f"invalid locale: {locale!r}")
        return self.dir / f"{locale}.jsonl"

    def _load(self, locale: str) -> list[ReviewTicket]:
        stamp = self._disk_stamp(locale)
        if locale in self._cache and self._stamp.get(locale) == stamp:
            return self._cache[locale]
        path = self.path_for(locale)
        out: list[ReviewTicket] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ticket = ReviewTicket.from_dict(raw)
                if ticket is not None:
                    out.append(ticket)
        self._cache[locale] = out
        self._stamp[locale] = stamp
        return out

    def _rewrite(self, locale: str, tickets: list[ReviewTicket]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        lines = [t.to_json() for t in tickets]
        rewrite_text_locked(
            self.path_for(locale),
            "\n".join(lines) + ("\n" if lines else ""),
        )
        self._cache[locale] = tickets
        self._stamp[locale] = self._disk_stamp(locale)

    def open_tickets(self, locale: str) -> list[ReviewTicket]:
        return [
            t for t in self._load(locale)
            if t.status in {STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED}
        ]

    def list_tickets(
        self, locale: str, status: str | None = None,
    ) -> list[ReviewTicket]:
        """Every ticket, or those with one stored status."""
        tickets = self._load(locale)
        if status is None:
            return list(tickets)
        return [t for t in tickets if t.status == status]

    def find_open(self, locale: str, namespace: str, key: str) -> ReviewTicket | None:
        sk = state_key(namespace, key)
        for t in self.open_tickets(locale):
            if state_key(t.namespace, t.key) == sk:
                return t
        return None

    def owner_of(self, namespace: str, key: str) -> str | None:
        from ..core.keyglob import key_glob_matches

        for pattern, owner in self.ownership.items():
            if key_glob_matches(pattern, namespace, key):
                return owner
        return None

    def overdue(self, locale: str, days: float, now: datetime | None = None) -> list[ReviewTicket]:
        """Open tickets older than ``days`` that were not escalated yet."""
        now = now or datetime.now(timezone.utc)
        out: list[ReviewTicket] = []
        for ticket in self.open_tickets(locale):
            if ticket.escalated_at:
                continue
            try:
                created = datetime.fromisoformat(ticket.created_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (now - created).total_seconds() >= days * 86400:
                out.append(ticket)
        return out

    def mark_escalated(self, locale: str, ticket_ids: list[str]) -> None:
        tickets = self._load(locale)
        stamp = now_iso()
        for ticket in tickets:
            if ticket.id in ticket_ids:
                ticket.escalated_at = stamp
        self._rewrite(locale, tickets)

    def _append(self, locale: str, tickets: list[ReviewTicket]) -> None:
        """Append new tickets as JSONL lines (locked, same schema as a rewrite)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(locale)
        for ticket in tickets:
            append_text_line(path, ticket.to_json())

    def enqueue(
        self,
        *,
        locale: str,
        namespace: str,
        key: str,
        reason: str,
        source: str | None = None,
        current: str | None = None,
        assignee: str | None = None,
        status: str = STATUS_OPEN,
        opened_by: str | None = None,
        title: str | None = None,
    ) -> ReviewTicket:
        """Create or refresh an open ticket for the key.

        With no explicit ``assignee`` a new ticket gets the ``[ownership]`` owner, if any.
        """
        return self.enqueue_many([{
            "locale": locale, "namespace": namespace, "key": key,
            "reason": reason, "source": source, "current": current,
            "assignee": assignee, "status": status,
            "opened_by": opened_by, "title": title,
        }])[0]

    def enqueue_many(self, items: list[dict]) -> list[ReviewTicket]:
        """Batch :meth:`enqueue`: one write per locale. Same dedup as ``enqueue``.

        Each item takes the ``enqueue`` keyword fields. New tickets are appended;
        refreshing an existing ticket rewrites that locale's file once.
        """
        out: list[ReviewTicket] = []
        new_by_locale: dict[str, list[ReviewTicket]] = {}
        dirty: set[str] = set()
        open_idx: dict[str, dict[str, ReviewTicket]] = {}
        for item in items:
            locale = item["locale"]
            namespace = item.get("namespace") or ""
            key = item["key"]
            assignee = item.get("assignee")
            if assignee is None:
                assignee = self.owner_of(namespace, key)
            ts = now_iso()
            tickets = self._load(locale)
            if locale not in open_idx:
                idx: dict[str, ReviewTicket] = {}
                for t in self.open_tickets(locale):
                    idx.setdefault(state_key(t.namespace, t.key), t)
                open_idx[locale] = idx
            existing = open_idx[locale].get(state_key(namespace, key))
            if existing is not None:
                existing.reason = item["reason"]
                existing.updated_at = ts
                if item.get("source") is not None:
                    existing.source = item["source"]
                if item.get("current") is not None:
                    existing.current = item["current"]
                if assignee is not None:
                    existing.assignee = assignee
                dirty.add(locale)
                out.append(existing)
                continue
            ticket = ReviewTicket(
                id=uuid.uuid4().hex[:12],
                locale=locale,
                namespace=namespace,
                key=key,
                reason=item["reason"],
                status=item.get("status") or STATUS_OPEN,
                assignee=assignee,
                created_at=ts,
                updated_at=ts,
                source=item.get("source"),
                current=item.get("current"),
                opened_by=item.get("opened_by") or "system",
                title=item.get("title"),
            )
            tickets.append(ticket)
            if ticket.status in {STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED}:
                open_idx[locale].setdefault(state_key(namespace, key), ticket)
            new_by_locale.setdefault(locale, []).append(ticket)
            out.append(ticket)
        for locale in dirty:
            self._rewrite(locale, self._load(locale))  # covers this locale's new tickets
        for locale, fresh in new_by_locale.items():
            if locale not in dirty:
                self._append(locale, fresh)
        return out

    def add_comment(self, locale: str, ticket_id: str, author: str, body: str) -> bool:
        tickets = self._load(locale)
        for t in tickets:
            if t.id == ticket_id:
                t.comments.append({
                    "ts": now_iso(), "author": author, "body": body,
                })
                t.updated_at = now_iso()
                self._rewrite(locale, tickets)
                return True
        return False

    def set_status(
        self,
        locale: str,
        ticket_id: str,
        status: str,
        *,
        assignee: str | None = None,
        actor: str | None = None,
    ) -> bool:
        if status not in STATUSES:
            return False
        tickets = self._load(locale)
        for t in tickets:
            if t.id == ticket_id:
                stamp = now_iso()
                if status != t.status:
                    t.events.append({
                        "ts": stamp, "actor": actor or "system", "kind": "status",
                        "from": t.status, "to": status,
                    })
                if assignee is not None and assignee != (t.assignee or ""):
                    t.events.append({
                        "ts": stamp, "actor": actor or "system", "kind": "assignee",
                        "from": t.assignee, "to": assignee or None,
                    })
                t.status = status
                t.updated_at = stamp
                if assignee is not None:
                    t.assignee = assignee or None
                self._rewrite(locale, tickets)
                return True
        return False


def open_review_queue(cfg) -> ReviewQueue:
    """The project's queue, with ``[ownership]`` applied to new tickets."""
    return ReviewQueue(cfg.review_root(), getattr(cfg, "ownership", None))
