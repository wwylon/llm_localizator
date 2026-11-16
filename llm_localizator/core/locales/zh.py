"""Chinese (Simplified)."""

from __future__ import annotations

from dataclasses import replace

from .base import LocaleProfile, fullwidth_punctuation_check

PROFILE = LocaleProfile(
    code="zh",
    name="Chinese (Simplified)",
    script="cjk",
    segmented=False,
    plural_categories=("other",),
    gettext_plural_forms="nplurals=1; plural=0;",
    expansion_band=(0.35, 0.8),
    typography_prompt="Use “ ” for quotation marks and 《 》 for titles. Use full-width punctuation (，。？！：；) and no spaces between Chinese characters.",
    typography_checks=(
        fullwidth_punctuation_check(
            "zh-fullwidth-punctuation",
            "\u3400-\u9fff",
            good="你好，世界。",
            bad="你好,世界.",
        ),
    ),
)

VARIANTS = {
    "zh-TW": replace(
        PROFILE,
        code="zh-TW",
        name="Chinese (Traditional)",
        aliases=("zh-Hant", "zh-Hant-TW", "zh-HK"),
        typography_prompt=(
            "Traditional Chinese: use 「 」 for quotation marks (nested: 『 』) and 《 》 for "
            "titles. Use full-width punctuation (，。？！：；) and no spaces between "
            "Chinese characters."
        ),
    ),
}
