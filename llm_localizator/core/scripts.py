"""Writing-system tables shared by quality scoring and script checks.

Neither ``quality`` nor ``script_checks`` owns these. Both import from here
so they do not import each other.
"""

from __future__ import annotations

import functools

from .locales import profile
from ._script_ranges import SCRIPT_RANGES

__all__ = [
    "SCRIPT_RANGES",
    "SCRIPT_PROMPT_NAMES",
    "expected_script",
    "char_script",
    "script_prompt_rule",
]

SCRIPT_PROMPT_NAMES: dict[str, str] = {
    "latin": "Latin",
    "cyrillic": "Cyrillic",
    "greek": "Greek",
    "arabic": "Arabic",
    "hebrew": "Hebrew",
    "cjk": "Chinese/Japanese/Korean (CJK)",
    "thai": "Thai",
    "devanagari": "Devanagari",
    "georgian": "Georgian",
    "armenian": "Armenian",
    "bengali": "Bengali",
    "gurmukhi": "Gurmukhi",
    "gujarati": "Gujarati",
    "tamil": "Tamil",
    "telugu": "Telugu",
    "kannada": "Kannada",
    "malayalam": "Malayalam",
    "sinhala": "Sinhala",
    "lao": "Lao",
    "tibetan": "Tibetan",
    "myanmar": "Myanmar",
    "khmer": "Khmer",
    "ethiopic": "Ethiopic",
    "thaana": "Thaana",
}


def expected_script(locale: str) -> str:
    """Primary writing system for *locale* (from its language profile)."""
    return profile(locale).script


@functools.lru_cache(maxsize=4096)
def char_script(ch: str) -> str | None:
    """Return the writing-system name for an alphabetic character, or None."""
    o = ord(ch)
    for name, ranges in SCRIPT_RANGES.items():
        for lo, hi in ranges:
            if lo <= o <= hi:
                return name
    return None


def script_prompt_rule(locale: str, language: str) -> str:
    """Locale-aware script instruction shared with script checks."""
    expected = expected_script(locale)
    expected_name = SCRIPT_PROMPT_NAMES.get(expected, expected)
    foreign = [
        SCRIPT_PROMPT_NAMES[s]
        for s in (
            "cjk", "cyrillic", "arabic", "hebrew", "thai", "greek",
            "devanagari", "latin",
        )
        if s != expected and s in SCRIPT_PROMPT_NAMES
    ]
    # Latin is never "foreign" for non-Latin targets (brands / ICU / loanwords).
    if expected != "latin":
        foreign = [n for n in foreign if n != "Latin"]
    foreign_list = ", ".join(foreign)
    latin_note = (
        " Latin letters are allowed in placeholders and brand names."
        if expected != "latin"
        else " Latin letters in placeholders and brand names are fine."
    )
    return (
        f"Write only in the {language} writing system ({expected_name}). "
        "ICU placeholder names are English code identifiers and must stay in Latin "
        "letters inside `{...}` — never translate or transliterate them. "
        f"Never mix in foreign scripts such as {foreign_list}."
        f"{latin_note}"
    )
