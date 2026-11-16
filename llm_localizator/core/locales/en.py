"""English."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="en",
    name="English",
    gettext_plural_forms="nplurals=2; plural=(n != 1);",
    decimal_mark=".",
    stopwords=frozenset({
        "the", "and", "of", "to", "in", "is", "are", "was", "were",
        "that", "for", "with", "this", "from", "have", "has", "an", "a",
    }),
)
