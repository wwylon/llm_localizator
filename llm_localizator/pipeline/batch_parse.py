"""Shared JSON-array batch parse for translate / back-translate."""

from __future__ import annotations

from ..providers._prompt_utils import parse_json_array

__all__ = ["parse_batch_strings"]


def parse_batch_strings(raw: str, expected: int) -> list[str | None]:
    """Parse a JSON array of ``expected`` strings; pad with None on mismatch."""
    parsed = parse_json_array(raw)
    if parsed is None or len(parsed) != expected:
        return [None] * expected
    return [str(v).strip() if v is not None else None for v in parsed]
