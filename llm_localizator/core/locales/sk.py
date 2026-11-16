"""Slovak."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="sk",
    name="Slovak",
    plural_categories=("one", "few", "many", "other"),
    plural_example="{n, plural, one {# bod} few {# body} many {# bodu} other {# bodov}}",
    gettext_plural_forms="nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;",
    expansion_band=(1.1, 1.5),
    decimal_mark=",",
    english_word_collisions=frozenset({"a", "to"}),
    typography_prompt="Use „ “ for quotation marks.",
)
