"""Per-key discussion threads: comments, @mentions and a resolved state (ADR-94).

A thread belongs to one source key (``namespace.key``) and is shared by every locale; it holds
questions about the English text or the translation, never text that reaches the catalogue.
The store is a local JSON file; nothing leaves the machine. Callers hold the project mutation
lock (ADR-24) to write.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .io import atomic_write_text, read_json
from .state import now_iso

__all__ = ["DiscussionStore", "discussions_path", "parse_mentions"]

_VERSION = 1
_MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9][\w.-]*)")


def discussions_path(cfg) -> Path:
    return cfg.state_root() / "discussions.json"


def parse_mentions(text: str) -> list[str]:
    """Distinct ``@name`` mentions in order of appearance, without the ``@``."""
    return list(dict.fromkeys(m.rstrip(".-") for m in _MENTION.findall(text)))


class DiscussionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_project(cls, cfg) -> "DiscussionStore":
        return cls(discussions_path(cfg))

    def items(self) -> dict[str, dict[str, Any]]:
        try:
            raw = read_json(self.path)
        except (OSError, ValueError):
            return {}
        items = raw.get("items") if isinstance(raw, dict) else None
        return items if isinstance(items, dict) else {}

    def get(self, ref: str) -> dict[str, Any] | None:
        return self.items().get(ref)

    def _write(self, items: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _VERSION, "items": items}
        atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def add(self, ref: str, *, text: str, by: str) -> dict[str, Any]:
        """Append a comment; a comment on a resolved thread reopens it."""
        items = self.items()
        thread = items.setdefault(ref, {"ref": ref, "comments": [], "resolved": False})
        thread["comments"].append({
            "n": len(thread["comments"]) + 1, "by": by, "at": now_iso(), "text": text,
            "mentions": parse_mentions(text),
        })
        thread["resolved"] = False
        thread.pop("resolved_by", None)
        thread.pop("resolved_at", None)
        self._write(items)
        return thread

    def set_resolved(self, ref: str, resolved: bool, by: str) -> dict[str, Any] | None:
        items = self.items()
        thread = items.get(ref)
        if thread is None:
            return None
        thread["resolved"] = resolved
        if resolved:
            thread["resolved_by"], thread["resolved_at"] = by, now_iso()
        else:
            thread.pop("resolved_by", None)
            thread.pop("resolved_at", None)
        self._write(items)
        return thread

    def open_counts(self) -> dict[str, int]:
        """``namespace.key`` of every unresolved thread, each counting one."""
        return {ref: 1 for ref, t in self.items().items() if not t.get("resolved")}
