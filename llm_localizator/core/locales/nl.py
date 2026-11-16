"""Dutch."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="nl",
    name="Dutch",
    gettext_plural_forms="nplurals=2; plural=(n != 1);",
    expansion_band=(1.2, 1.6),
    hyphenate=True,
    decimal_mark=",",
    english_word_collisions=frozenset({"in", "is", "of", "was"}),
)
