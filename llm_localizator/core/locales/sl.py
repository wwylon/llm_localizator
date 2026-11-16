"""Slovenian."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="sl",
    name="Slovenian",
    plural_categories=("one", "two", "few", "other"),
    plural_example="{n, plural, one {# točka} two {# točki} few {# točke} other {# točk}}",
    gettext_plural_forms="nplurals=4; plural=(n%100==1 ? 0 : n%100==2 ? 1 : n%100==3 || n%100==4 ? 2 : 3);",
    expansion_band=(1.1, 1.5),
    decimal_mark=",",
    english_word_collisions=frozenset({"a", "in", "to"}),
    typography_prompt="Use „ “ for quotation marks.",
)
