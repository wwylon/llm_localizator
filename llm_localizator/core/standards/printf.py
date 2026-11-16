"""printf-family replacement tokens.

``%s``, ``%d``, ``%v``, ``%(name)s``, ``%1$s``. ``%%`` is an escaped percent,
not a token. A bare ``%`` in ``100%`` is not a token. No plural syntax.
"""

from __future__ import annotations

import re

__all__ = ["PrintfStandard"]

# Conversion letters used by C printf, Go fmt, and Python %.
_CONV = "diouxXfFeEgGaAcspnvbT"
_PLAIN = re.compile(
    rf"(?=\S)(?:\d+\$)?[-+ #0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlLzjt]*[{_CONV}]"
)


class PrintfStandard:
    id = "printf"
    has_plurals = False

    def tokens(self, text: str) -> set[str]:
        found, _err = _scan(text)
        return found

    def sequential_counts(self, text: str) -> dict[str, int]:
        """Counts of unnumbered, unnamed tokens: ``%s of %s`` must keep both."""
        counts: dict[str, int] = {}
        for tok in _scan_list(text):
            if "$" in tok or tok.startswith("%("):
                continue
            counts[tok] = counts.get(tok, 0) + 1
        return counts

    def syntax_error(self, text: str) -> str | None:
        _found, err = _scan(text)
        return err

    def plural_categories(self, text: str) -> set[str] | None:
        return None

    def missing_plural_keys(self, messages: dict[str, str], locale: str) -> list[str]:
        return []


def _scan_list(text: str) -> list[str]:
    found: list[str] = []
    _scan(text, found)
    return found


def _scan(text: str, order: list[str] | None = None) -> tuple[set[str], str | None]:
    out: set[str] = set()
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "%":
            i += 1
            continue
        if i + 1 < n and text[i + 1] == "%":
            i += 2
            continue
        if i + 1 < n and text[i + 1] == "(":
            close = text.find(")", i + 2)
            if close < 0:
                return out, "unclosed printf placeholder"
            name = text[i + 2:close]
            if not re.fullmatch(r"\w+", name):
                return out, "invalid printf placeholder name"
            conv_at = close + 1
            if conv_at >= n or text[conv_at] not in _CONV:
                return out, "printf placeholder missing conversion"
            end = conv_at + 1
            out.add(text[i:end])
            if order is not None:
                order.append(text[i:end])
            i = end
            continue
        match = _PLAIN.match(text, i + 1)
        if match is None:
            i += 1
            continue
        end = match.end()
        if end < n and text[end].isalpha():
            # ``100% sure`` is a percent sign, not ``% s``.
            i += 1
            continue
        out.add(text[i:end])
        if order is not None:
            order.append(text[i:end])
        i = end
    return out, None
