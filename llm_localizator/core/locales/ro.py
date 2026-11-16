"""Romanian."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="ro",
    name="Romanian",
    plural_categories=("one", "few", "other"),
    plural_example="{n, plural, one {# punct} few {# puncte} other {# de puncte}}",
    gettext_plural_forms="nplurals=3; plural=(n==1 ? 0 : (n==0 || (n%100>0 && n%100<20)) ? 1 : 2);",
    expansion_band=(1.1, 1.5),
    decimal_mark=",",
    english_word_collisions=frozenset({"a", "an", "in"}),
)
