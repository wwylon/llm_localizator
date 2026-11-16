"""The shape of a language profile.

A profile holds everything the tool knows about one language. Each language has
its own module in this package; nothing about a language lives anywhere else.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .._script_ranges import SCRIPT_RANGES as _SCRIPT_RANGES

__all__ = [
    "CLDR_CATEGORIES",
    "KNOWN_SCRIPTS",
    "LocaleProfile",
    "TypographyCheck",
    "regex_check",
    "fullwidth_punctuation_check",
]

CLDR_CATEGORIES = frozenset({"zero", "one", "two", "few", "many", "other"})

KNOWN_SCRIPTS: frozenset[str] = frozenset(_SCRIPT_RANGES)


@dataclass(frozen=True)
class TypographyCheck:
    """One typography rule (V34). Every rule ships a passing and a failing example.

    A rule is either a ``pattern`` (fires when it matches the translation) or a
    ``predicate`` (fires when it returns True).
    """

    id: str
    message: str
    good: str
    bad: str
    pattern: re.Pattern[str] | None = None
    predicate: Callable[[str], bool] | None = None

    def __post_init__(self) -> None:
        if (self.pattern is None) == (self.predicate is None):
            raise ValueError(f"{self.id}: give exactly one of pattern or predicate")

    def fires(self, text: str) -> bool:
        if self.predicate is not None:
            return bool(self.predicate(text))
        assert self.pattern is not None
        return self.pattern.search(text) is not None


def regex_check(id: str, pattern: str, message: str, *, good: str, bad: str) -> TypographyCheck:
    return TypographyCheck(id, message, good, bad, pattern=re.compile(pattern))


def fullwidth_punctuation_check(
    id: str, letters: str, *, good: str, bad: str,
) -> TypographyCheck:
    """Half-width ``, . ? ! : ;`` right after a CJK letter should be full-width.

    ``letters`` is a regex character-class body for the language's own letters.
    The mark must end a phrase (followed by space, end of text, or more CJK), so
    file names such as ``設定.json`` are left alone.
    """
    return regex_check(
        id,
        rf"[{letters}][,.?!:;](?=$|\s|[{letters}])",
        "use full-width punctuation (，。？！：；) after Chinese/Japanese text",
        good=good,
        bad=bad,
    )


@dataclass(frozen=True)
class LocaleProfile:
    """Everything known about one language or regional variant."""

    code: str
    name: str
    # Writing system and layout.
    script: str = "latin"
    direction: str = "ltr"
    segmented: bool = True  # False for scripts written without spaces between words
    # Plurals.
    plural_categories: tuple[str, ...] = ("one", "other")
    plural_example: str | None = None
    gettext_plural_forms: str | None = None
    # Length and layout.
    expansion_band: tuple[float, float] | None = None
    hyphenate: bool = False
    # Numbers: the decimal mark this language expects, or None when unknown.
    decimal_mark: str | None = None
    # Quality checks.
    suspicious_digraphs: frozenset[str] = frozenset()
    inflects: bool = False  # approved glossary terms may appear inflected (V13)
    capitalizes_nouns: bool = False  # nouns keep a capital: never lowercase to match the source
    # Common function words. Used to spot untranslated leftovers of this language (V33).
    stopwords: frozenset[str] = frozenset()
    # English stopwords that are ordinary words in this language (V33 must ignore them).
    english_word_collisions: frozenset[str] = frozenset()
    # Typography: guidance sent to the model, and rules checked afterwards (V34).
    typography_prompt: str = ""
    typography_checks: tuple[TypographyCheck, ...] = ()
    # Grammar: rules the model must follow (cases, agreement, numerals, UI verb
    # moods, how to phrase around placeholders), sent with every translate,
    # improve and judge prompt; vetted source→target pairs that show them; and
    # cheap heuristics checked afterwards (V45). Keep the prompt short: it is in
    # every request. A heuristic must be reliable; the judge covers the rest.
    grammar_prompt: str = ""
    grammar_examples: tuple[tuple[str, str], ...] = ()
    grammar_checks: tuple[TypographyCheck, ...] = ()
    # Formality (V40): wording sent to the model when a register is set explicitly,
    # and pronoun patterns that mark each register. Both must be unambiguous words.
    informal_prompt: str = ""
    formal_prompt: str = ""
    informal_marker: re.Pattern[str] | None = None
    formal_marker: re.Pattern[str] | None = None
    # Offered when a person picks a language (variants such as fr-CA are; a bare
    # "pt" is not, because pt-PT and pt-BR differ).
    selectable: bool = True
    aliases: tuple[str, ...] = ()
