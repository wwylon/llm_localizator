"""Shared scan regexes for JSX / HTML user-visible text."""

from __future__ import annotations

import re

__all__ = [
    "HTML_TEXT",
    "T_PRESENT",
    "USER_ATTR",
]

# JSX/HTML text between tags (prose helper decides; do not require ASCII).
HTML_TEXT = re.compile(r">\s*([^<>{}\n]{2,}?)\s*<")

# Real ``t(`` call (word boundary) — not ``setHeight(`` / ``get(``.
T_PRESENT = re.compile(r"\bt\s*\(")

# Common user-visible attributes.
USER_ATTR = re.compile(
    r"""\b(placeholder|title|alt|aria-label)\s*=\s*(["'])(.*?)\2""",
    re.DOTALL | re.IGNORECASE,
)
