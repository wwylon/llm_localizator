"""Shared prompt parsing. Not a provider."""

from __future__ import annotations

import json

__all__ = ["PAYLOAD_MARKER", "extract_sources", "numbered_lines", "parse_json_array"]

#: The batch prompt numbers its *rules* as well as its payload, so a naive
#: "every ``N. ...`` line" scan returns the rules too and every batch looks
#: malformed. Parsing starts after this marker.
PAYLOAD_MARKER = "Strings to translate:"


def parse_json_array(raw: str) -> list | None:
    """Extract and parse the first JSON array from *raw*.

    Returns the parsed list, or ``None`` if no valid array is found.
    Callers are responsible for validating element types and length.
    """
    # Try the whole string first (handles models that reply with only an array).
    stripped = raw.strip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    # Fall back to bracket scan for models that add preamble text.
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def extract_sources(prompt: str, schema: dict | None) -> list[str]:
    """Pull UI strings out of an llm_localizator prompt for machine translation.

    Handles both batch (numbered-list) and single-string prompt shapes.
    """
    if schema is not None:
        lines = numbered_lines(prompt)
        if lines:
            return lines
    marker = "String to translate:"
    if marker in prompt:
        return [prompt.split(marker, 1)[1].strip()]
    if PAYLOAD_MARKER in prompt:
        lines = numbered_lines(prompt)
        if lines:
            return lines
    return []


def numbered_lines(prompt: str) -> list[str]:
    """Recover the ``1. text`` items a batch prompt embeds."""
    _, marker, payload = prompt.partition(PAYLOAD_MARKER)
    body = payload if marker else prompt

    out: list[str] = []
    for line in body.splitlines():
        head, sep, rest = line.strip().partition(". ")
        if not (sep and head.isdigit()):
            continue
        # Drop the bracketed hints the prompt builder appends
        # ([key:], [context:], [max N chars], …).
        idx = rest.find("  [")
        if idx != -1:
            rest = rest[:idx]
        out.append(rest.strip())
    return out
