"""Italian."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="it",
    name="Italian",
    gettext_plural_forms="nplurals=2; plural=(n != 1);",
    decimal_mark=",",
    english_word_collisions=frozenset({"a", "in"}),
)
