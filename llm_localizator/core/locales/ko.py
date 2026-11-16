"""Korean."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="ko",
    name="Korean",
    script="cjk",
    plural_categories=("other",),
    plural_example="{n, plural, other {#점}}",
    gettext_plural_forms="nplurals=1; plural=0;",
    expansion_band=(0.55, 0.9),
)
