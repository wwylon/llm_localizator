"""Burmese."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="my",
    name="Burmese",
    script="myanmar",
    segmented=False,
    typography_prompt="No spaces between words. Use ။ for the sentence end.",
)
