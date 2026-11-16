"""Language reference helpers.

The data itself lives in ``core/locales/`` (one module per language). These are
the two lookups most of the code base wants.
"""

from __future__ import annotations

from .locales import known_locales, locale_name, profile

__all__ = [
    "known_locales",
    "language_name",
    "required_plural_categories",
]


def language_name(locale: str) -> str:
    """Human-readable language name for prompts; falls back to the code itself."""
    return locale_name(locale)


def required_plural_categories(locale: str) -> set[str]:
    """CLDR plural categories a translation into ``locale`` must supply."""
    return set(profile(locale).plural_categories)
