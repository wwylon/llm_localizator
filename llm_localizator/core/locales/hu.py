"""Hungarian."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="hu",
    name="Hungarian",
    decimal_mark=",",
    english_word_collisions=frozenset({"a", "is"}),
    typography_prompt="Use „ ” for quotation marks.",
)
