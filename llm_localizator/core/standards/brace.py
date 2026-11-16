"""Brace replacement tokens: Python str.format, C# composite, C++ fmtlib.

``{name}``, ``{0}``, ``{0:spec}``. An ICU plural is a syntax error here, not a
plural. ``{{`` and ``}}`` are escaped braces, not tokens.
"""

from __future__ import annotations

import re

__all__ = ["BraceStandard"]

_ICU = re.compile(r"\s*\w+\s*,\s*(?:plural|select|selectordinal)\b")
_FIELD = re.compile(
    r"\s*(?:[A-Za-z_]\w*|\d+)(?:![sra])?(?::[^}]*)?\s*"
)


class BraceStandard:
    id = "brace"
    has_plurals = False

    def tokens(self, text: str) -> set[str]:
        found, _err = _scan(text)
        return found

    def syntax_error(self, text: str) -> str | None:
        _found, err = _scan(text)
        return err

    def plural_categories(self, text: str) -> set[str] | None:
        return None

    def missing_plural_keys(self, messages: dict[str, str], locale: str) -> list[str]:
        return []


def _scan(text: str) -> tuple[set[str], str | None]:
    out: set[str] = set()
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("{{", i) or text.startswith("}}", i):
            i += 2
            continue
        if text[i] != "{":
            i += 1
            continue
        rest = text[i + 1:]
        if _ICU.match(rest):
            return out, "ICU plural is not valid brace syntax"
        close = text.find("}", i + 1)
        if close < 0 or "{" in text[i + 1:close]:
            return out, "unclosed '{'"
        inner = text[i + 1:close]
        if not _FIELD.fullmatch(inner):
            return out, "invalid brace placeholder"
        out.add(inner.strip())
        i = close + 1
    return out, None
