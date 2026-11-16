"""Hebrew."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="he",
    name="Hebrew",
    script="hebrew",
    direction="rtl",
    plural_categories=("one", "two", "many", "other"),
    plural_example="{n, plural, one {נקודה אחת} two {שתי נקודות} many {# נקודות} other {# נקודות}}",
    gettext_plural_forms="nplurals=4; plural=(n==1 ? 0 : n==2 ? 1 : n>10 && n%10==0 ? 2 : 3);",
    expansion_band=(0.7, 1.2),
    typography_prompt="Right-to-left text. Use the geresh (׳) for abbreviations and the gershayim (״) for acronyms.",
)
