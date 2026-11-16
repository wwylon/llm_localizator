"""Indonesian."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="id",
    name="Indonesian",
    plural_categories=("other",),
    gettext_plural_forms="nplurals=1; plural=0;",
    expansion_band=(0.9, 1.2),
)
