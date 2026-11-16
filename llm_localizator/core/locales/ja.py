"""Japanese."""

from __future__ import annotations

from .base import LocaleProfile, fullwidth_punctuation_check

PROFILE = LocaleProfile(
    code="ja",
    name="Japanese",
    script="cjk",
    segmented=False,
    plural_categories=("other",),
    gettext_plural_forms="nplurals=1; plural=0;",
    expansion_band=(0.4, 0.9),
    typography_prompt="Use 。for sentence-end punctuation, 「…」 for inline quotes. Do not add spaces between Japanese characters and inline Latin words.",
    typography_checks=(
        fullwidth_punctuation_check(
            "ja-fullwidth-punctuation",
            "\u3040-\u30ff\u3400-\u9fff",
            good="こんにちは、世界。",
            bad="こんにちは,世界.",
        ),
    ),
)
