"""Finnish."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="fi",
    name="Finnish",
    expansion_band=(1.2, 1.7),
    hyphenate=True,
    decimal_mark=",",
    typography_prompt="Use ” ” (the same closing mark on both sides) for quotation marks.",
)
