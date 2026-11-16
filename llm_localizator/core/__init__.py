"""Pure, zero-I/O localisation primitives.

Nothing in this package touches the filesystem, the network, or any project
layout. Everything here is a function of its arguments, which is what makes the
validator usable standalone -- in CI, with no LLM and no configuration.
"""

from __future__ import annotations

from .cldr import language_name, required_plural_categories
from .hash import src_hash, structure_signature
from .hyphens import apply_soft_hyphens, pyphen_available
from .icu import extract_placeholders, extract_plural_categories, top_level_brace_spans
from .locale_policy import LocalePolicy
from .locales import LocaleProfile, known_locales, profile
from .validate import (
    check_translation_length,
    glossary_violations,
    term_pattern,
    validate_translation,
)

__all__ = [
    "LocalePolicy",
    "LocaleProfile",
    "apply_soft_hyphens",
    "check_translation_length",
    "extract_placeholders",
    "extract_plural_categories",
    "glossary_violations",
    "known_locales",
    "language_name",
    "profile",
    "pyphen_available",
    "required_plural_categories",
    "src_hash",
    "structure_signature",
    "term_pattern",
    "top_level_brace_spans",
    "validate_translation",
]
