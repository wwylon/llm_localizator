"""Helpers shared by the literal lexers: comments, escapes, balanced brackets, char literals.

Split out of ``scan/literals.py`` (M3); ``lexers.iter_literals`` picks one per language.
"""

from __future__ import annotations

import re

from ...core.languages import SourceLanguage


def _only_indent_before(text: str, index: int) -> bool:
    start = text.rfind("\n", 0, index) + 1
    return text[start:index].strip() == ""


def _skip_line_comment(text: str, index: int) -> int:
    end = text.find("\n", index)
    return len(text) if end < 0 else end


def _skip_block(text: str, index: int, end_mark: str) -> int:
    found = text.find(end_mark, index)
    return len(text) if found < 0 else found + len(end_mark)


_ESCAPES = {"n": "\n", "t": "\t", "r": ""}


def _skip_balanced(text: str, index: int, opener: str, closer: str) -> int:
    """Index after the bracket that closes the one at *index*, skipping nested quoted strings."""
    depth, i, n = 0, index, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            i = j
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _read_escaped(text: str, index: int, quote: str, interp: str = "") -> tuple[int, str] | None:
    """Read a quoted string starting at *index* (on the opening quote).

    ``interp`` names the interpolation syntax whose expressions may hold quotes of their own:
    ``swift`` (backslash, paren, expr) or ``dollar`` (``${expr}``, Kotlin/Scala/Dart). Each expression becomes ``{…}``.
    """
    i = index + 1
    n = len(text)
    chars: list[str] = []
    while i < n:
        ch = text[i]
        if interp == "swift" and ch == "\\" and text.startswith("(", i + 1):
            i = _skip_balanced(text, i + 1, "(", ")")
            chars.append("{…}")
            continue
        if interp == "dollar" and ch == "$" and text.startswith("{", i + 1):
            i = _skip_balanced(text, i + 1, "{", "}")
            chars.append("{…}")
            continue
        if ch == "\\":
            if i + 1 >= n:
                return None
            chars.append(_ESCAPES.get(text[i + 1], text[i + 1]))
            i += 2
            continue
        if ch == quote:
            return i + 1, "".join(chars)
        if ch == "\n" and quote != "`":
            return None  # a stray quote must not swallow the rest of the file
        chars.append(ch)
        i += 1
    return None


def skip_to(pattern: re.Pattern, text: str, index: int) -> int:
    """First index at or after *index* where *pattern* (a class of characters that can start a token) matches.

    M4: the lexers stepped one character at a time through plain code; a character none of their branches reacts to
    only ever led to ``i += 1``, so jumping straight to the next candidate gives the same tokens.
    """
    m = pattern.search(text, index)
    return m.start() if m else len(text)


_SCRIPT_STARTS: dict[str, re.Pattern] = {}


def script_starts(lang: SourceLanguage) -> re.Pattern:
    """Characters that can open a comment, string, char literal or heredoc in *lang*."""
    pattern = _SCRIPT_STARTS.get(lang.id)
    if pattern is None:
        chars = {"'", '"', "`", "<"}
        chars.update(mark[0] for mark in lang.line_comments if mark)
        if lang.block_comment and lang.block_comment[0]:
            chars.add(lang.block_comment[0][0])
        pattern = re.compile("[" + "".join(re.escape(c) for c in sorted(chars)) + "]")
        _SCRIPT_STARTS[lang.id] = pattern
    return pattern


def _starts_comment(text: str, index: int, lang: SourceLanguage) -> str | None:
    for mark in lang.line_comments:
        if text.startswith(mark, index):
            return "line"
    if lang.block_comment and text.startswith(lang.block_comment[0], index):
        return "block"
    return None


#: A char/rune literal: ``'a'``, ``'"'``, ``'\''``, ``'\n'``, ``'é'``, ``'\u{1F600}'``. Not a Rust lifetime (``'a``).
_CHAR_LITERAL = re.compile(r"""'(?:\\(?:u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[^\n])|[^'\\\n])'""")


def _char_literal_end(text: str, i: int) -> int | None:
    """End of the char literal at *i*, or None (M2: ``'"'`` opened a fake string in Go, C# and Rust)."""
    m = _CHAR_LITERAL.match(text, i)
    return m.end() if m else None
