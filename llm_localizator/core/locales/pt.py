"""Portuguese."""

from __future__ import annotations

from dataclasses import replace

from .base import LocaleProfile

PROFILE = LocaleProfile(
    code="pt",
    name="Portuguese",
    expansion_band=(1.1, 1.35),
    decimal_mark=",",
    english_word_collisions=frozenset({"a"}),
    selectable=False,
)

VARIANTS = {
    "pt-PT": replace(
        PROFILE,
        code="pt-PT",
        name="European Portuguese",
        gettext_plural_forms="nplurals=2; plural=(n != 1);",
        selectable=True,
    ),
    "pt-BR": replace(
        PROFILE,
        code="pt-BR",
        name="Brazilian Portuguese",
        gettext_plural_forms="nplurals=2; plural=(n > 1);",
        selectable=True,
    ),
}
