"""Croatian."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="hr",
    name="Croatian",
    plural_categories=("one", "few", "other"),
    plural_example="{n, plural, one {# bod} few {# boda} other {# bodova}}",
    gettext_plural_forms="nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    expansion_band=(1.1, 1.5),
    decimal_mark=",",
    english_word_collisions=frozenset({"a", "to"}),
    typography_prompt="Use „ ” for quotation marks.",
)
