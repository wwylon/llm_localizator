"""Lexer for C and C++: ordinary and raw string literals.

Split out of ``scan/literals.py`` (M3); ``lexers.iter_literals`` picks one per language.
"""

from __future__ import annotations

import re

from ...core.languages import SourceLanguage
from ..base import line_number
from .common import _read_escaped, _skip_block, _skip_line_comment, _starts_comment, skip_to


def _cpp(text: str):
    lang = SourceLanguage("cpp", (), ("//",), ("/*", "*/"), (), "literal", "cpp")
    i = skip_to(_STARTS, text, 0)
    n = len(text)
    while i < n:
        kind = _starts_comment(text, i, lang)
        if kind == "line":
            i = _skip_line_comment(text, i)
            continue
        if kind == "block":
            i = _skip_block(text, i + 2, "*/")
            continue
        raw = _cpp_raw_at(text, i)
        if raw is not None:
            end, literal = raw
            yield line_number(text, i), literal
            i = end
            continue
        if text[i] == '"':
            parsed = _read_escaped(text, i, '"')
            if parsed is None:
                i += 1
                continue
            end, literal = parsed
            yield line_number(text, i), literal
            i = end
            continue
        i = skip_to(_STARTS, text, i + 1)


#: Characters that can open a comment, a string or a raw string (M4).
_STARTS = re.compile(r'[/"R]')


def _cpp_raw_at(text: str, index: int) -> tuple[int, str] | None:
    """Match an optional encoding prefix plus ``R\"delim( ... )delim\"``."""
    window = text[max(0, index - 3):index + 2]
    if not window.endswith('R"') and not text.startswith('R"', index):
        return None
    start = index if text.startswith('R"', index) else index
    # Allow the caller to land on R.
    if not text.startswith('R"', start):
        return None
    delim_end = text.find("(", start + 2)
    if delim_end < 0 or delim_end - (start + 2) > 16:
        return None
    delim = text[start + 2:delim_end]
    if not re.fullmatch(r"[\w]*", delim):
        return None
    closer = ")" + delim + '"'
    body = delim_end + 1
    end = text.find(closer, body)
    if end < 0:
        return None
    return end + len(closer), text[body:end]
