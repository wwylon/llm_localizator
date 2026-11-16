"""Source-change log: why a translation went stale (ADR-52).

One JSONL line per change of an English source string, in ``<state>/source_history.jsonl``.
``sync`` and ``push-strings`` append; the editor reads the latest line for a key. The log is
advisory, so a repeated call with the same new text writes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from .state import now_iso, state_key

__all__ = ["SOURCE_HISTORY_NAME", "SourceHistory"]

SOURCE_HISTORY_NAME = "source_history.jsonl"
TRIGGER = "source-changed"


class SourceHistory:
    def __init__(self, state_root: Path) -> None:
        self.path = Path(state_root) / SOURCE_HISTORY_NAME

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    def latest(self, namespace: str, key: str) -> dict | None:
        sk = state_key(namespace, key)
        found = None
        for row in self._rows():
            if state_key(row.get("namespace", ""), row.get("key", "")) == sk:
                found = row
        return found

    def record_changes(self, changes: list[tuple[str, str, str, str]]) -> int:
        """Append ``(namespace, key, prev_src, next_src)`` rows; returns how many were new."""
        rows = self._rows()
        last: dict[str, str] = {}
        for row in rows:
            last[state_key(row.get("namespace", ""), row.get("key", ""))] = row.get("next_src", "")
        fresh: list[dict] = []
        for namespace, key, prev_src, next_src in changes:
            sk = state_key(namespace, key)
            if not prev_src or prev_src == next_src or last.get(sk) == next_src:
                continue
            last[sk] = next_src
            fresh.append({
                "trigger": TRIGGER, "namespace": namespace, "key": key,
                "prev_src": prev_src, "next_src": next_src, "timestamp": now_iso(),
            })
        if fresh:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in fresh)
            # Append instead of rewriting the whole log; start on a fresh line
            # if the file lacks a trailing newline.
            if self.path.exists() and self.path.stat().st_size:
                with self.path.open("rb") as fh:
                    fh.seek(-1, 2)
                    if fh.read(1) != b"\n":
                        text = "\n" + text
            with self.path.open("a", encoding="utf-8", newline="") as fh:
                fh.write(text)
        return len(fresh)
