"""Arabic."""

from __future__ import annotations

from .base import LocaleProfile, regex_check

PROFILE = LocaleProfile(
    code="ar",
    name="Arabic",
    script="arabic",
    direction="rtl",
    plural_categories=("zero", "one", "two", "few", "many", "other"),
    plural_example="{n, plural, zero {# نقطة} one {نقطة واحدة} two {نقطتان} few {# نقاط} many {# نقطة} other {# نقطة}}",
    gettext_plural_forms="nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5);",
    expansion_band=(1.1, 1.5),
    inflects=True,
    typography_prompt="Right-to-left text. Use Arabic punctuation: ؟ (question mark), ، (comma) and ؛ (semicolon). Use « » or “ ” for quotation marks.",
    typography_checks=(
        regex_check(
            "ar-punctuation",
            r"[\u0621-\u064a\u0671-\u06d3]\s*[?;,]",
            "use Arabic punctuation (؟ ؛ ،) after Arabic text",
            good="هل تريد الحفظ؟",
            bad="هل تريد الحفظ?",
        ),
    ),
)
