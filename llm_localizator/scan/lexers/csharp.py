"""Lexer for C#: regular and verbatim (``@"…"``) strings; char literals are skipped.

Split out of ``scan/literals.py`` (M3); ``lexers.iter_literals`` picks one per language.
"""

from __future__ import annotations

import re

from ...core.languages import SourceLanguage
from ..base import line_number
from .common import _char_literal_end, _read_escaped, _skip_block, _skip_line_comment, _starts_comment, skip_to


def _csharp(text: str):
    lang = SourceLanguage("csharp", (), ("//",), ("/*", "*/"), (), "literal", "csharp")
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
        if text[i] == "'" and (char_end := _char_literal_end(text, i)):
            i = char_end   # a char: ``'"'`` must not open a string
            continue
        if text.startswith('"""', i):
            end = text.find('"""', i + 3)  # C# 11 raw string literal
            if end >= 0:
                yield line_number(text, i), " ".join(text[i + 3:end].split())
                i = end + 3
                continue
        verbatim = text.startswith(('@"', '$"', '$@"', '@$"'), i)
        # ``_read_verbatim`` takes the index of the opening quote (M2: it was handed one past it).
        if text.startswith('$@"', i) or text.startswith('@$"', i):
            parsed = _read_verbatim(text, i + 2)
        elif text.startswith('@"', i):
            parsed = _read_verbatim(text, i + 1)
        elif text.startswith('$"', i) or text[i] == '"':
            at = i + 1 if text.startswith('$"', i) else i
            parsed = _read_escaped(text, at, '"')
        else:
            parsed = None
        if parsed is not None and (verbatim or text[i] == '"' or text.startswith('$"', i)):
            end, literal = parsed
            yield line_number(text, i), literal
            i = end
            continue
        i = skip_to(_STARTS, text, i + 1)


#: Characters that can open a comment, char literal or (verbatim/interpolated/raw) string (M4).
_STARTS = re.compile(r"""[/'"@$]""")


def _read_verbatim(text: str, index: int) -> tuple[int, str] | None:
    """C# verbatim string. *index* is on the opening quote. ``""`` is one quote."""
    if index >= len(text) or text[index] != '"':
        return None
    i = index + 1
    chars: list[str] = []
    while i < len(text):
        if text.startswith('""', i):
            chars.append('"')
            i += 2
            continue
        if text[i] == '"':
            return i + 1, "".join(chars)
        chars.append(text[i])
        i += 1
    return None
