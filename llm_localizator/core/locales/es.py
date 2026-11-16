"""Spanish."""

from __future__ import annotations

import re

from .base import LocaleProfile, TypographyCheck

_URL = re.compile(r"https?://\S+")


def _missing_opening(text: str, opening: str, closing: str) -> bool:
    text = _URL.sub("", text)
    return text.count(closing) > text.count(opening)


PROFILE = LocaleProfile(
    code="es",
    name="Spanish",
    gettext_plural_forms="nplurals=2; plural=(n != 1);",
    expansion_band=(1.1, 1.35),
    decimal_mark=",",
    english_word_collisions=frozenset({"a"}),
    typography_prompt="Open every question with ¿ and every exclamation with ¡, and close with ? and !. Use « » for quotation marks.",
    typography_checks=(
        TypographyCheck(
            "es-question-marks",
            "open questions with ¿",
            good="¿Guardar cambios?",
            bad="Guardar cambios?",
            predicate=lambda text: _missing_opening(text, "¿", "?"),
        ),
        TypographyCheck(
            "es-exclamation-marks",
            "open exclamations with ¡",
            good="¡Listo!",
            bad="Listo!",
            predicate=lambda text: _missing_opening(text, "¡", "!"),
        ),
    ),
)
