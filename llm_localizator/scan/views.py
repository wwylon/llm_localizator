"""Text views with the same line numbers as the source (M3, audit D3).

Several scanners cut a file into views — markup without script, code without comments, one language out of a
template — and every view must keep each line where it was, so hits point at the right line. These helpers replace
characters with spaces and keep every newline.
"""

from __future__ import annotations

import re

__all__ = ["blank", "blank_match", "blank_spans", "MarkupView", "scan_markup_view"]

_NOT_NEWLINE = re.compile(r"[^\n]")


def blank(chunk: str) -> str:
    """Same number of lines, no content."""
    return _NOT_NEWLINE.sub(" ", chunk)


def blank_match(m: re.Match) -> str:
    """``pattern.sub(blank_match, text)``: blank every match."""
    return blank(m.group())


def blank_spans(text: str, spans) -> str:
    """Blank each ``(start, end)`` span of *text* in one pass (spans may overlap or come in any order)."""
    spans = sorted((max(0, a), min(len(text), b)) for a, b in spans if b > a)
    if not spans:
        return text
    out, pos = [], 0
    for a, b in spans:
        if b <= pos:
            continue
        a = max(a, pos)
        out.append(text[pos:a])
        out.append(blank(text[a:b]))
        pos = b
    out.append(text[pos:])
    return "".join(out)


_LETTER = re.compile(r"[^\W\d_]")


class MarkupView:
    """A markup view whose template expressions became one plain stand-in word (audit D2).

    The HTML line rules reject braces, so ``Hello {{ name }}`` is scanned as ``Hello zzvarzz`` and the hit is tidied
    back to ``Hello {x}``. Used by the Vue/Svelte, server-template, indented-markup (Pug, Slim, Haml), Astro/MDX and
    templ scanners.
    """

    SLOT = "zzvarzz"

    @classmethod
    def slot(cls, m: re.Match) -> str:
        """``pattern.sub(MarkupView.slot, text)``: an expression becomes the slot word, keeping its newlines."""
        return cls.SLOT + "\n" * m.group().count("\n")

    @classmethod
    def slot_text(cls, pattern: re.Pattern[str], text: str) -> str:
        """Every match of *pattern* becomes the bare slot word (one-line views)."""
        return pattern.sub(cls.SLOT, text)

    @classmethod
    def tidy(cls, hits) -> list:
        """Hits with the slot word shown as ``{x}``; a hit that was only expressions is dropped."""
        from dataclasses import replace

        kept = []
        for hit in hits:
            if cls.SLOT in hit.text:
                if not _LETTER.search(hit.text.replace(cls.SLOT, "")):
                    continue  # only expressions: nothing to translate
                hit = replace(hit, text=hit.text.replace(cls.SLOT, "{x}"))
            kept.append(hit)
        return kept


def scan_markup_view(raw_scanner, rel: str, markup: str, result) -> None:
    """Scan a markup view (expressions already replaced by the slot word) and tidy the slot out of the hits."""
    before = len(result.hardcoded)
    raw_scanner.scan_text(rel, markup.split("\n"), True, result)
    # Only the new tail is rebuilt (M4 P1: copying the whole list per file was O(hits)).
    result.hardcoded[before:] = MarkupView.tidy(result.hardcoded[before:])
