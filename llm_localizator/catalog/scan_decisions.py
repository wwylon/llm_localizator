"""Persisted user decisions on scan results (ADR-55).

A scan finds hardcoded strings and candidate text collections; the user decides what
is localized. The decision is kept apart from ``scan_cache.json`` (a pure cache that a
rescan may discard) and is keyed on a stable id, not on a line number, so it survives
edits and ``--refresh``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .io import atomic_write_text
from .state import now_iso
from .io import read_json

__all__ = [
    "ACCEPTED", "APPLIED", "IGNORED", "KIND_COLLECTION", "KIND_HIT", "ScanDecisions",
    "collection_id", "decisions_path", "hit_id",
]

ACCEPTED = "accepted"
IGNORED = "ignored"
APPLIED = "applied"
STATUSES = (ACCEPTED, IGNORED, APPLIED)
KIND_HIT = "hit"
KIND_COLLECTION = "collection"
_VERSION = 1


def _digest(*parts: str) -> str:
    return hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:12]


def hit_id(file: str, text: str) -> str:
    """Stable id of a hardcoded string: file and normalised text, never the line."""
    return _digest(KIND_HIT, file.replace("\\", "/"), " ".join(text.split()))


def collection_id(name: str, root: str) -> str:
    return _digest(KIND_COLLECTION, name, root.replace("\\", "/"))


def decisions_path(cfg) -> Path:
    return cfg.state_root() / "scan_decisions.json"


class ScanDecisions:
    """Read-modify-write store; callers hold the project mutation lock (ADR-24) to write."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_project(cls, cfg) -> "ScanDecisions":
        return cls(decisions_path(cfg))

    def items(self) -> dict[str, dict[str, Any]]:
        try:
            raw = read_json(self.path)
        except (OSError, ValueError):
            return {}
        items = raw.get("items") if isinstance(raw, dict) else None
        return items if isinstance(items, dict) else {}

    def exists(self) -> bool:
        return bool(self.items())

    def get(self, item_id: str) -> dict[str, Any] | None:
        return self.items().get(item_id)

    def status_of(self, item_id: str) -> str | None:
        entry = self.get(item_id)
        return entry.get("status") if entry else None

    def _write(self, items: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _VERSION, "items": items}
        atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def decide(
        self,
        item_id: str,
        status: str,
        *,
        kind: str = KIND_HIT,
        by: str = "",
        **fields: Any,
    ) -> dict[str, Any]:
        """Record a decision. An ``applied`` item is never demoted by accept or ignore."""
        if status not in STATUSES:
            raise ValueError(f"unknown decision status {status!r}")
        items = self.items()
        current = items.get(item_id) or {}
        if current.get("status") == APPLIED and status != APPLIED:
            return current
        entry = {**current, **{k: v for k, v in fields.items() if v not in (None, "")}}
        entry.update({"kind": kind, "status": status, "by": by, "ts": now_iso()})
        items[item_id] = entry
        self._write(items)
        return entry

    def reset(self, item_id: str) -> bool:
        items = self.items()
        if item_id not in items:
            return False
        del items[item_id]
        self._write(items)
        return True

    def summary(self, live_ids: set[str] | None = None, kind: str = KIND_HIT) -> dict[str, int]:
        """Counts per status; with ``live_ids`` also ``pending`` and ``orphaned``."""
        counts = {ACCEPTED: 0, IGNORED: 0, APPLIED: 0}
        seen: set[str] = set()
        orphaned = 0
        for item_id, entry in self.items().items():
            if entry.get("kind", KIND_HIT) != kind:
                continue
            status = entry.get("status")
            if status in counts:
                counts[status] += 1
            seen.add(item_id)
            if live_ids is not None and item_id not in live_ids:
                orphaned += 1
        if live_ids is not None:
            counts["pending"] = len(live_ids - seen)
            counts["orphaned"] = orphaned
        return counts
