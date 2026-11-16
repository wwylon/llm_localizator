"""Khmer."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="km",
    name="Khmer",
    script="khmer",
    segmented=False,
    typography_prompt="No spaces between words. Use ។ (Khmer full stop) for sentence-end punctuation.",
)
