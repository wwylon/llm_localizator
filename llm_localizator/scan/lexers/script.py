"""Lexer for the script-quoted languages (Java, Kotlin, Swift, Ruby, PHP, Rust, Dart, …): text blocks, heredocs, interpolation.

Split out of ``scan/literals.py`` (M3); ``lexers.iter_literals`` picks one per language.
"""

from __future__ import annotations

import re

from ...core.languages import SourceLanguage
from ..base import line_number
from .common import (
    _char_literal_end, _read_escaped, _skip_block, _skip_line_comment, _starts_comment, script_starts, skip_to,
)


def _script(text: str, lang: SourceLanguage):
    starts = script_starts(lang)
    i = skip_to(starts, text, 0)
    n = len(text)
    while i < n:
        kind = _starts_comment(text, i, lang)
        if kind == "line":
            i = _skip_line_comment(text, i)
            continue
        if kind == "block" and lang.block_comment:
            i = _skip_block(text, i + len(lang.block_comment[0]), lang.block_comment[1])
            continue
        ch = text[i]
        if text.startswith('"""', i):
            # Java/Kotlin/Swift/C# text block: everything up to the closing triple quote, indentation removed.
            end = text.find('"""', i + 3)
            if end >= 0:
                yield line_number(text, i), " ".join(text[i + 3:end].split())
                i = end + 3
                continue
        if lang.id == "php" and text.startswith("<<<", i):
            heredoc = _HEREDOC.match(text, i)
            if heredoc:
                yield line_number(text, i), " ".join(heredoc.group(2).split())
                i = heredoc.end()
                continue
        if lang.id == "ruby" and text.startswith("<<", i):
            heredoc = _RUBY_HEREDOC.match(text, i)
            if heredoc:
                yield line_number(text, i), " ".join(heredoc.group(2).split())
                i = heredoc.end()
                continue
        if lang.id == "rust" and ch in {"'", "`"}:
            # Lifetimes (``'a``) and char literals are never copy; skip a whole char so ``'"'`` opens no string.
            i = (_char_literal_end(text, i) if ch == "'" else None) or i + 1
            continue
        if ch in {"'", '"', "`"}:
            parsed = _read_escaped(text, i, ch, _INTERP.get(lang.id, ""))
            if parsed is None:
                i += 1
                continue
            end, literal = parsed
            yield line_number(text, i), literal
            i = end
            continue
        i = skip_to(starts, text, i + 1)


_INTERP = {"swift": "swift", "kotlin": "dollar", "scala": "dollar", "dart": "dollar"}
#: Ruby heredoc: ``<<~TEXT … TEXT`` (also ``<<-`` and quoted ids).
_RUBY_HEREDOC = re.compile(r"""<<[~-]?['"]?([A-Z_]\w*)['"]?[ \t]*\r?\n(.*?)\r?\n[ \t]*\1\b""", re.S)
#: PHP heredoc/nowdoc: ``<<<EOT … EOT;``
_HEREDOC = re.compile(r"""<<<[ \t]*['"]?(\w+)['"]?[ \t]*\r?\n(.*?)\r?\n[ \t]*\1\b;?""", re.S)
