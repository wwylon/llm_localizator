"""Model drafts waiting for a person to accept them (ADR-91).

A draft is one model translation for one key, kept apart from the catalogue, state, history
and TM until accepted. The record carries the source text it was made from, so a draft whose
source has since changed is recognised as stale and never applied. Callers hold the project
mutation lock (ADR-24) to write.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import atomic_write_text, read_json
from .state import now_iso

__all__ = ["DraftStore", "draft_id", "drafts_path"]

_VERSION = 1


def draft_id(locale: str, namespace: str, key: str) -> str:
    return f"{locale}:{namespace}.{key}"


def drafts_path(cfg) -> Path:
    return cfg.state_root() / "drafts.json"


class DraftStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_project(cls, cfg) -> "DraftStore":
        return cls(drafts_path(cfg))

    def items(self) -> dict[str, dict[str, Any]]:
        try:
            raw = read_json(self.path)
        except (OSError, ValueError):
            return {}
        items = raw.get("items") if isinstance(raw, dict) else None
        return items if isinstance(items, dict) else {}

    def get(self, did: str) -> dict[str, Any] | None:
        return self.items().get(did)

    def _write(self, items: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _VERSION, "items": items}
        atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def put(self, locale: str, namespace: str, key: str, **fields: Any) -> dict[str, Any]:
        """Store a draft; a newer draft for the same key replaces the older one."""
        items = self.items()
        entry = {
            "locale": locale, "namespace": namespace, "key": key, "ts": now_iso(), **fields,
        }
        items[draft_id(locale, namespace, key)] = entry
        self._write(items)
        return entry

    def discard(self, did: str) -> bool:
        items = self.items()
        if did not in items:
            return False
        del items[did]
        self._write(items)
        return True
