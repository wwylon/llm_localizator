"""Sample values for short placeholder frames (ADR-124).

A source like ``{rank} of {suit}`` has one word outside its placeholders. Sent
alone (masked or not) the model sees a bare "of" and guesses: Polish got
"{rank} część {suit}". Shown filled — "Ace of Spades" — the same model writes
"{rank} {suit}". This module decides which sources are frames and picks the
sample values; the prompt builders render them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..core.icu import PLURAL_HEAD_RE, bare_placeholder_spans, top_level_brace_spans

__all__ = [
    "FRAME_WORD_LIMIT",
    "frame_words",
    "has_icu_choice",
    "is_placeholder_frame",
    "frame_sample_values",
    "fill_frame",
    "restore_frame_values",
]

#: A frame has fewer than this many words outside its placeholders.
FRAME_WORD_LIMIT = 3

_WORD_RE = re.compile(r"[^\W\d_]+")
_NAME_RE = re.compile(r"\{\s*(\w+)")

# (name pattern, sample). First match wins; names are lower-cased first.
_NAMED_SAMPLES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), v) for p, v in (
        (r"rank", "Ace"),
        (r"suit", "Spades"),
        (r"^(?:from|start|first|lo|min|begin)$", "1"),
        (r"^(?:to|end|last|hi|max|until)$", "20"),
        (r"pages?_?(?:count|total)|^pages$", "12"),
        (r"page", "3"),
        (r"pct|percent", "42"),
        (r"name|user|who|player|author|owner|person", "Alex"),
        (r"file|path|doc", "report.pdf"),
        (r"date|day", "14 March"),
        (r"time|clock", "14:30"),
        (r"model", "llama3"),
        (r"lang|locale", "Polish"),
        (r"(?:count|total|matched|num|number|size|len|length|amount|^n$|^k$|^m$)", "135"),
    )
)
# Distinct numbers for numeric names with no better match, so each value maps back to one name.
_SPARE_NUMBERS = ("7", "48", "250", "9", "64")


def _outside_text(source: str) -> str:
    out = source
    for _s, _e, span in sorted(bare_placeholder_spans(source), key=lambda t: -t[0]):
        out = out[:_s] + " " + out[_e:]
    return out


def frame_words(source: str) -> int:
    """Words outside the bare placeholders of *source*."""
    return len(_WORD_RE.findall(_outside_text(source or "")))


def has_icu_choice(source: str) -> bool:
    """True when *source* carries a top-level plural / select / selectordinal argument."""
    return any(PLURAL_HEAD_RE.match(span[1:-1]) for span in top_level_brace_spans(source or ""))


def is_placeholder_frame(source: str) -> bool:
    """A short frame: at least one bare placeholder and 1–2 words around it, no ICU choice."""
    if not source or "\n" in source or has_icu_choice(source):
        return False
    if not bare_placeholder_spans(source):
        return False
    return 0 < frame_words(source) < FRAME_WORD_LIMIT


def _sample_for(name: str, used: set[str]) -> str:
    low = name.lower()
    for pattern, value in _NAMED_SAMPLES:
        if pattern.search(low) and value not in used:
            return value
    for value in _SPARE_NUMBERS:
        if value not in used:
            return value
    return name.replace("_", " ").title()


def frame_sample_values(
    source: str, preview: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """``{"{rank}": "Ace", ...}`` for every bare placeholder in *source*.

    Values from the key's ``preview_values`` (ADR-109 sample values kept in the
    context entry) win; the rest are plausible samples chosen by name.
    """
    preview = preview or {}
    out: dict[str, str] = {}
    used: set[str] = set()
    for _s, _e, span in bare_placeholder_spans(source or ""):
        if span in out:
            continue
        m = _NAME_RE.match(span)
        name = m.group(1) if m else span.strip("{} ")
        raw = preview.get(name)
        value = str(raw).strip() if raw is not None and str(raw).strip() else ""
        if not value or value in used:
            value = _sample_for(name, used)
        used.add(value)
        out[span] = value
    return out


def fill_frame(source: str, samples: Mapping[str, str]) -> str:
    """*source* with each placeholder span replaced by its sample value."""
    out = source
    for span, value in samples.items():
        out = out.replace(span, value)
    return out


def restore_frame_values(text: str, samples: Mapping[str, str] | None) -> str:
    """Put a placeholder back where the model wrote its sample value instead.

    Only for a placeholder that is missing from *text* and whose sample occurs
    exactly once, so a real word is never replaced.
    """
    if not samples:
        return text
    out = text
    for span, value in samples.items():
        if span in out or not value:
            continue
        if len(re.findall(rf"(?<!\w){re.escape(value)}(?!\w)", out)) == 1:
            out = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", lambda _m, s=span: s, out)
    return out
