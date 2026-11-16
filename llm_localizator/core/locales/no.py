"""Norwegian."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="no",
    name="Norwegian",
    decimal_mark=",",
    english_word_collisions=frozenset({"for", "is", "to"}),
    typography_prompt="Use « » for quotation marks.",
)
