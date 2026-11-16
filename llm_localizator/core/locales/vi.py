"""Vietnamese."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="vi",
    name="Vietnamese",
    plural_categories=("other",),
    gettext_plural_forms="nplurals=1; plural=0;",
    expansion_band=(0.75, 1.1),
    english_word_collisions=frozenset({"an", "in", "to"}),
)
