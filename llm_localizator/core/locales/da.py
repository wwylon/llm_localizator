"""Danish."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="da",
    name="Danish",
    decimal_mark=",",
    english_word_collisions=frozenset({"for", "have", "is", "to"}),
    typography_prompt="Use » « (or „ “) for quotation marks.",
)
