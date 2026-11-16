"""Swedish."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="sv",
    name="Swedish",
    decimal_mark=",",
    english_word_collisions=frozenset({"is"}),
    typography_prompt="Use ” ” (the same closing mark on both sides) for quotation marks.",
)
