"""Lexer for Go: interpreted and raw (backquoted) strings; runes are skipped.

Split out of ``scan/literals.py`` (M3); ``lexers.iter_literals`` picks one per language.
"""

from __future__ import annotations

import re

from ...core.languages import SourceLanguage
from ..base import line_number
from .common import _char_literal_end, _read_escaped, _skip_block, _skip_line_comment, _starts_comment, skip_to


def _go(text: str):
    lang = SourceLanguage("go", (), ("//",), ("/*", "*/"), (), "literal", "go")
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
        if text[i] == "`":
            end = text.find("`", i + 1)
            if end < 0:
                return
            yield line_number(text, i), text[i + 1:end]
            i = end + 1
            continue
        if text[i] == "'" and (char_end := _char_literal_end(text, i)):
            i = char_end   # a rune: ``'"'`` must not open a string
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


#: Characters that can open a comment, a raw string, a rune or a string (M4).
_STARTS = re.compile(r"""[/`'"]""")
