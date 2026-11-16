"""Thai."""

from __future__ import annotations

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="th",
    name="Thai",
    script="thai",
    segmented=False,
    plural_categories=("other",),
    gettext_plural_forms="nplurals=1; plural=0;",
    expansion_band=(0.6, 0.95),
    typography_prompt="Thai is written without spaces between words; use a space only to separate phrases or sentences. Do not add a full stop (period) at the end of short UI labels.",
)
