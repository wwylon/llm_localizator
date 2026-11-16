"""French."""

from __future__ import annotations

import re
from dataclasses import replace

from .base import LocaleProfile, regex_check

PROFILE = LocaleProfile(
    code="fr",
    name="French",
    gettext_plural_forms="nplurals=2; plural=(n > 1);",
    expansion_band=(1.1, 1.4),
    decimal_mark=",",
    english_word_collisions=frozenset({"a", "an"}),
    informal_prompt="Address the reader with informal 'tu' (tu, toi, ton, ta, tes).",
    formal_prompt="Address the reader with formal 'vous' (vous, votre, vos).",
    informal_marker=re.compile(r"\b(?:tu|toi|ton|ta|tes)\b", re.I),
    formal_marker=re.compile(r"\b(?:vous|votre|vos)\b", re.I),
    typography_prompt="Put a non-breaking space (U+00A0) before : ; ! ? and before », and one after «. Use « » for quotation marks (e.g. « bonjour »).",
    typography_checks=(
        regex_check(
            "fr-space-before-punctuation",
            r"(?<=[^\W\d_])[;!?:](?=\s|$)",
            "put a space before : ; ! ?",
            good="Erreur : fichier introuvable",
            bad="Erreur: fichier introuvable",
        ),
    ),
)

VARIANTS = {
    "fr-CA": replace(
        PROFILE,
        code="fr-CA",
        name="French (Canada)",
        typography_prompt=(
            "Canadian French: put a non-breaking space (U+00A0) before a colon (:) and "
            "inside « » quotation marks. Do NOT put a space before ; ! or ?."
        ),
        typography_checks=(
            regex_check(
                "fr-ca-space-before-colon",
                r"(?<=[^\W\d_]):(?=\s|$)",
                "put a space before a colon",
                good="Erreur : fichier introuvable",
                bad="Erreur: fichier introuvable",
            ),
        ),
    ),
}
