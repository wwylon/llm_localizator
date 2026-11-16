"""Inline do-not-translate markers inside a string (C-034, ADR-86).

An HTML element marked ``translate="no"`` or ``class="notranslate"`` is kept verbatim,
tags and content, the way the W3C attribute and Google's ``notranslate`` class define it.
Pure text functions; no I/O and no project knowledge.
"""

from __future__ import annotations

import re
from collections import Counter

__all__ = ["dnt_spans", "has_dnt_markers", "check_dnt_spans"]

_OPEN_RE = re.compile(r"<([A-Za-z][A-Za-z0-9]*)\b([^<>]*?)(/?)>")
_MARK_RE = re.compile(
    r"""\btranslate\s*=\s*["']?no\b|\bclass\s*=\s*["'][^"']*\bnotranslate\b""",
    re.IGNORECASE,
)


def _element_end(text: str, name: str, start: int) -> int:
    """Index just past the closing tag that balances the open tag ending at ``start``."""
    pattern = re.compile(rf"<(/?){re.escape(name)}\b[^<>]*?(/?)>", re.IGNORECASE)
    depth = 1
    for match in pattern.finditer(text, start):
        if match.group(2):  # self-closing inner tag
            continue
        depth += -1 if match.group(1) else 1
        if depth == 0:
            return match.end()
    return -1


def dnt_spans(text: str) -> list[tuple[int, int, str]]:
    """Outermost marked elements as ``(start, end, element_text)``, in order."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    body = text or ""
    while True:
        match = _OPEN_RE.search(body, pos)
        if match is None:
            return out
        if not _MARK_RE.search(match.group(2)):
            pos = match.end()
            continue
        if match.group(3):  # <img translate="no" />: the tag is the whole element
            end = match.end()
        else:
            end = _element_end(body, match.group(1), match.end())
            if end < 0:  # unclosed: leave it to the HTML integrity check
                pos = match.end()
                continue
        out.append((match.start(), end, body[match.start():end]))
        pos = end


def has_dnt_markers(text: str) -> bool:
    return bool(dnt_spans(text))


def check_dnt_spans(source: str, translated: str) -> str | None:
    """V42: every marked element of the source must appear unchanged in the translation."""
    want = Counter(span for _s, _e, span in dnt_spans(source))
    if not want:
        return None
    have = Counter(span for _s, _e, span in dnt_spans(translated))
    missing = [span for span, n in want.items() if have.get(span, 0) < n]
    if not missing:
        return None
    shown = ", ".join(repr(m if len(m) <= 40 else m[:37] + "...") for m in missing[:3])
    return f"do-not-translate element changed or missing: {shown}"
