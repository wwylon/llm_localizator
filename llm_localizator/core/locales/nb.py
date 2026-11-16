"""Norwegian (Bokmal)."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="nb",
    name="Norwegian (Bokmal)",
    decimal_mark=",",
    english_word_collisions=frozenset({"for", "is", "to"}),
    typography_prompt="Use « » for quotation marks.",
)
