"""Turkish."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="tr",
    name="Turkish",
    gettext_plural_forms="nplurals=2; plural=(n > 1);",
    expansion_band=(0.95, 1.3),
    decimal_mark=",",
)
