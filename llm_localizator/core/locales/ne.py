"""Nepali."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="ne",
    name="Nepali",
    script="devanagari",
    typography_prompt="Use the danda (।) as the full stop.",
)
