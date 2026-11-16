"""Lexer for Python: string prefixes, triple quotes, raw strings; a triple-quoted string opening its line is skipped.

Split out of ``scan/literals.py`` (M3); ``lexers.iter_literals`` picks one per language.
"""

from __future__ import annotations

import re

from ..base import line_number
from .common import _only_indent_before, _read_escaped, _skip_line_comment, skip_to


_PY_PREFIX = re.compile(r"(?<![\w])([rRuUbBfF]{0,2})([\"'])")
#: Characters at which a comment, a string or a string prefix can start (M4).
_STARTS = re.compile(r"""[#"'rRuUbBfF]""")


def _python(text: str):
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "#":
            i = _skip_line_comment(text, i)
            continue
        match = _PY_PREFIX.match(text, i)
        if match is None:
            i = skip_to(_STARTS, text, i + 1)
            continue
        prefix = match.group(1)
        quote = match.group(2)
        start = match.start(2)
        triple = text.startswith(quote * 3, start)
        opener = quote * 3 if triple else quote
        raw = "r" in prefix.lower()
        content_at = start + len(opener)
        if triple and raw:
            end = text.find(opener, content_at)
            if end < 0:
                return
            literal = text[content_at:end]
            end_at = end + len(opener)
        elif triple:
            parsed = _read_until(text, content_at, opener)
            if parsed is None:
                return
            end_at, literal = parsed
        else:
            parsed = _read_escaped(text, start, quote) if not raw else _read_raw_single(text, start, quote)
            if parsed is None:
                i = start + 1
                continue
            end_at, literal = parsed
        if not (triple and _only_indent_before(text, match.start())):
            yield line_number(text, start), literal
        i = end_at


def _read_until(text: str, index: int, closer: str) -> tuple[int, str] | None:
    """Escaped read until *closer*, which may be more than one character."""
    i = index
    n = len(text)
    chars: list[str] = []
    while i < n:
        if text.startswith("\\", i) and i + 1 < n:
            chars.append(text[i + 1])
            i += 2
            continue
        if text.startswith(closer, i):
            return i + len(closer), "".join(chars)
        chars.append(text[i])
        i += 1
    return None


def _read_raw_single(text: str, index: int, quote: str) -> tuple[int, str] | None:
    end = text.find(quote, index + 1)
    if end < 0:
        return None
    return end + 1, text[index + 1:end]
