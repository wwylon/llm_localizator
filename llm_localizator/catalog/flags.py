"""JSONL developer flags shared by validation and improvement pipelines."""

from __future__ import annotations

import json
from pathlib import Path

from .jsonl import append_jsonl, iter_jsonl_objects, rewrite_jsonl_lines
from .state import state_key


class FlagStore:
    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None
        self._existing: set[tuple[object, object, object]] | None = None
        self.malformed = 0

    def _identities(self) -> set[tuple[object, object, object]]:
        if self._existing is None:
            self._existing = {
                (row.get("locale"), row.get("namespace"), row.get("key"))
                for row in self.rows()
            }
        return self._existing

    def invalidate(self) -> None:
        self._existing = None

    def rows(self) -> list[dict]:
        if self.path is None:
            return []
        out = [row for row, _raw in iter_jsonl_objects(self.path)]
        return out

    def grouped(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for row in self.rows():
            locale, namespace, key = row.get("locale"), row.get("namespace"), row.get("key")
            if locale and namespace is not None and key is not None:
                out.setdefault(str(locale), set()).add(state_key(str(namespace), str(key)))
        return out

    def append(self, row: dict) -> bool:
        if self.path is None:
            return False
        ident = (row.get("locale"), row.get("namespace"), row.get("key"))
        if ident in self._identities():
            return False
        append_jsonl(self.path, row)
        self._identities().add(ident)
        return True

    def resolve(self, locale: str, namespace: str, key: str) -> bool:
        """Drop ``(locale, namespace, key)`` from the flags file. Returns True if removed."""
        return self.resolve_many([(locale, namespace, key)]) > 0

    def resolve_many(self, idents) -> int:
        """Drop several ``(locale, namespace, key)`` rows in one rewrite; return how many."""
        wanted = set(idents)
        if not wanted or self.path is None or not self.path.exists():
            return 0
        removed = 0
        kept: list[str] = []
        for row, raw in iter_jsonl_objects(self.path):
            row_ident = (row.get("locale"), row.get("namespace"), row.get("key"))
            if row_ident in wanted:
                removed += 1
                continue
            kept.append(json.dumps(row, ensure_ascii=False))
        if not removed:
            return 0
        rewrite_jsonl_lines(self.path, kept)
        if self._existing is not None:
            self._existing -= wanted
        return removed

    def append_findings(self, findings, checks: set[str]) -> int:
        """Append many findings with one identity scan (no per-row fsync storm)."""
        if self.path is None:
            return 0
        known = self._identities()
        count = 0
        for finding in findings:
            if finding.check not in checks:
                continue
            ident = (finding.locale, finding.namespace, finding.key)
            if ident in known:
                continue
            append_jsonl(self.path, {
                "locale": finding.locale,
                "namespace": finding.namespace,
                "key": finding.key,
                "reason": f"{finding.check}: {finding.message}",
            })
            known.add(ident)
            count += 1
        return count
