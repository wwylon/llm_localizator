"""Hindi."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="hi",
    name="Hindi",
    script="devanagari",
    typography_prompt="Use the danda (।) as the full stop.",
)
