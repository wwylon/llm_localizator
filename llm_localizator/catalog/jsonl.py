"""Shared JSONL helpers — streaming reads, locked rewrite, malformed counts."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeVar

from .io import append_text_line, rewrite_text_locked

T = TypeVar("T")


def iter_jsonl_objects(path: Path) -> Iterator[tuple[dict, str]]:
    """Yield ``(obj, raw_line)`` for each parseable object line.

    Blank lines and malformed JSON are skipped. Callers that need a
    malformed count should use :func:`load_jsonl_objects`.
    """
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    yield raw, stripped
    except OSError:
        return


def load_jsonl_objects(
    path: Path,
    *,
    parse: Callable[[dict], T | None] | None = None,
) -> tuple[list[T | dict], int]:
    """Load objects; return ``(rows, malformed_count)``."""
    rows: list[T | dict] = []
    malformed = 0
    if not path.exists():
        return rows, 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(raw, dict):
                    malformed += 1
                    continue
                if parse is None:
                    rows.append(raw)
                    continue
                item = parse(raw)
                if item is None:
                    malformed += 1
                    continue
                rows.append(item)
    except OSError:
        pass
    return rows, malformed


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    append_text_line(path, json.dumps(obj, ensure_ascii=False))


def rewrite_jsonl_lines(path: Path, lines: list[str]) -> None:
    rewrite_text_locked(path, "\n".join(lines) + ("\n" if lines else ""))
