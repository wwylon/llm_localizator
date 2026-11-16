"""German."""

from __future__ import annotations

import re
from dataclasses import replace

from .base import LocaleProfile, regex_check

PROFILE = LocaleProfile(
    code="de",
    name="German",
    plural_categories=("one", "other"),
    gettext_plural_forms="nplurals=2; plural=(n != 1);",
    expansion_band=(1.2, 1.8),
    hyphenate=True,
    decimal_mark=",",
    suspicious_digraphs=frozenset({"ßä", "ßö", "äß", "äö", "äü", "öß", "öä", "öü", "üä", "üö"}),
    english_word_collisions=frozenset({"an", "in", "was"}),
    informal_prompt="Address the reader with informal 'du' (du, dich, dir, dein).",
    formal_prompt="Address the reader with formal 'Sie' (Sie, Ihnen, Ihr), always capitalised.",
    informal_marker=re.compile(r"\b(?:du|dich|dir|dein\w*)\b"),
    formal_marker=re.compile(r"(?<=[a-zäöüß,;] )(?:Sie|Ihnen)\b"),
    capitalizes_nouns=True,
    typography_prompt="Use „low-high\" quotation marks (U+201E / U+201C) for German quotes. Compound nouns must be written as one word.",
)

VARIANTS = {
    "de-CH": replace(
        PROFILE,
        code="de-CH",
        name="German (Switzerland)",
        decimal_mark=".",
        typography_prompt=(
            "Swiss German: use « » for quotation marks and write ss, never ß. "
            "Compound nouns must be written as one word."
        ),
        typography_checks=(
            regex_check(
                "de-ch-eszett",
                "ß",
                "Swiss German is written with ss, never ß",
                good="Strasse",
                bad="Straße",
            ),
        ),
    ),
}
