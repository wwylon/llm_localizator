"""Latin identifier vs prose token extraction for script / BT checks.

Env-style identifiers (``BRIDGE_SUPER_ADMIN_EMAILS``) must stay atomic —
splitting on ``_`` invents English words that falsely pass "Latin from source"
and distort back-translation Jaccard.
"""

from __future__ import annotations

import re

from .icu import extract_placeholders, top_level_brace_spans

__all__ = [
    "SCREAMING_SNAKE_RE",
    "strip_screaming_snake",
    "strip_icu_spans",
    "extract_identifier_spans",
    "extract_prose_latin_runs",
    "source_latin_allowlist",
]

# Env vars / config keys (BRIDGE_SUPER_ADMIN_EMAILS).
SCREAMING_SNAKE_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")

# Contiguous Latin letters (Basic + Latin Extended), length ≥ 2.
_PROSE_LATIN_RE = re.compile(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]{2,}")


def strip_screaming_snake(text: str) -> str:
    """Drop ALL_CAPS_SNAKE identifiers so BT overlap scores prose only."""
    return SCREAMING_SNAKE_RE.sub(" ", text or "")


def strip_icu_spans(text: str) -> str:
    """Replace top-level ICU ``{...}`` spans with spaces (names stay Latin)."""
    if not text:
        return ""
    out: list[str] = []
    pos = 0
    for span in top_level_brace_spans(text):
        idx = text.find(span, pos)
        if idx < 0:
            continue
        out.append(text[pos:idx])
        out.append(" ")
        pos = idx + len(span)
    out.append(text[pos:])
    return "".join(out)


def extract_identifier_spans(text: str) -> list[str]:
    """Return SCREAMING_SNAKE spans (case-sensitive, whole match)."""
    return SCREAMING_SNAKE_RE.findall(text or "")


def extract_prose_latin_runs(text: str) -> list[str]:
    """Latin letter runs after stripping ICU and identifier spans."""
    cleaned = strip_icu_spans(text or "")
    cleaned = SCREAMING_SNAKE_RE.sub(" ", cleaned)
    return _PROSE_LATIN_RE.findall(cleaned)


def source_latin_allowlist(source: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(identifiers, prose_casefold)`` allowed from the English source.

    Identifiers are case-sensitive whole spans. Prose tokens are casefolded.
    ICU placeholder names are added as prose (they may appear bare after mask
    restore) and as identifiers when they match SCREAMING_SNAKE.
    """
    identifiers = set(extract_identifier_spans(source))
    prose = {t.casefold() for t in extract_prose_latin_runs(source)}
    for name in extract_placeholders(source or ""):
        if SCREAMING_SNAKE_RE.fullmatch(name):
            identifiers.add(name)
        else:
            prose.add(name.casefold())
    return frozenset(identifiers), frozenset(prose)
