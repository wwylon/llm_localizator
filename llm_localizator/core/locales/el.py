"""Greek."""

from __future__ import annotations

from .base import LocaleProfile, regex_check

PROFILE = LocaleProfile(
    code="el",
    name="Greek",
    script="greek",
    typography_prompt="The Greek question mark is ; (a semicolon), never ?. Use « » for quotation marks.",
    typography_checks=(
        regex_check(
            "el-question-mark",
            r"[\u0370-\u03ff\u1f00-\u1fff]\s*\?",
            "use the Greek question mark ; instead of ?",
            good="Θέλετε να αποθηκεύσετε;",
            bad="Θέλετε να αποθηκεύσετε?",
        ),
    ),
)
