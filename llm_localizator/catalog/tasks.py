"""Translation tasks: a set of keys, one assignee per locale, an optional due date (ADR-92).

A task is a named work package, not a ticket: it lists keys and, per locale, who does them. It
holds no text and no status of its own; progress is read from the state store (a key is done
for a locale when a person verified it). Callers hold the project mutation lock (ADR-24) to write.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import atomic_write_text, read_json
from .state import is_verified, now_iso

__all__ = ["TaskStore", "task_progress", "tasks_path"]

_VERSION = 1


def tasks_path(cfg) -> Path:
    return cfg.state_root() / "tasks.json"


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_project(cls, cfg) -> "TaskStore":
        return cls(tasks_path(cfg))

    def items(self) -> dict[str, dict[str, Any]]:
        try:
            raw = read_json(self.path)
        except (OSError, ValueError):
            return {}
        items = raw.get("items") if isinstance(raw, dict) else None
        return items if isinstance(items, dict) else {}

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.items().get(task_id)

    def _write(self, items: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _VERSION, "items": items}
        atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def create(self, *, name: str, keys: list[str], assignees: dict[str, str], due: str,
               by: str) -> dict[str, Any]:
        items = self.items()
        n = 1 + max((int(i[2:]) for i in items if i[2:].isdigit()), default=0)
        task_id = f"T-{n:03d}"
        items[task_id] = {
            "id": task_id, "name": name, "keys": sorted(dict.fromkeys(keys)),
            "assignees": dict(assignees), "due": due, "created_by": by, "created_at": now_iso(),
        }
        self._write(items)
        return items[task_id]

    def delete(self, task_id: str) -> bool:
        items = self.items()
        if task_id not in items:
            return False
        del items[task_id]
        self._write(items)
        return True

    def assigned_keys(self, user: str, locale: str) -> set[str]:
        """``namespace.key`` the user may edit in ``locale`` through a task."""
        out: set[str] = set()
        for task in self.items().values():
            if task.get("assignees", {}).get(locale) == user:
                out.update(task.get("keys", []))
        return out


def task_progress(task: dict, state) -> dict[str, dict[str, int]]:
    """Per locale ``{done, total}``; done means verified in the state store."""
    keys = [k.partition(".")[::2] for k in task.get("keys", [])]
    out: dict[str, dict[str, int]] = {}
    for locale in task.get("assignees", {}):
        done = sum(1 for ns, key in keys if is_verified(state.entry(locale, ns, key)))
        out[locale] = {"done": done, "total": len(keys)}
    return out
