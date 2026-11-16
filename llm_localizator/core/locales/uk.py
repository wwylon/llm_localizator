"""Ukrainian."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="uk",
    name="Ukrainian",
    script="cyrillic",
    plural_categories=("one", "few", "many", "other"),
    plural_example="{n, plural, one {# бал} few {# бали} many {# балів} other {# бала}}",
    gettext_plural_forms="nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    expansion_band=(1.05, 1.4),
    decimal_mark=",",
    typography_prompt="Use « » for quotation marks (nested: „ “). Write dashes as an em dash (—) with spaces around it.",
)
