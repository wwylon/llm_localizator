"""pseudo (en-XX / en-XA) must mark every word and keep ICU syntax parseable.

Regression: argument names were masked as substrings, so "Current version:
{version}" kept the word "version", and the "n" in "{n, plural, one ...}"
survived inside "one" while "plural"/"other" were turned into X's.
"""

from __future__ import annotations

import re

import pytest

from llm_localizator.core.source_quality import pseudo_text


@pytest.mark.parametrize("value, tokens, expected", [
    ("Current version: {version}", {"version"}, "XXXXXXX XXXXXXX: {version}"),
    ("{n, plural, one {# image} other {# images}}", {"n"},
     "{n, plural, one {# XXXXX} other {# XXXXXX}}"),
    ("{done} of {total} done", {"done", "total"}, "{done} XX {total} XXXX"),
    ("Hand {lone, select, yes {alone} other {}}", {"lone"},
     "XXXX {lone, select, yes {XXXXX} other {}}"),
    ("{n, plural, offset:1 =0 {nobody} other {# more}}", {"n"},
     "{n, plural, offset:1 =0 {XXXXXX} other {# XXXX}}"),
    ("Click <b>Save</b> now", set(), "XXXXX <b>XXXX</b> XXX"),
    ("Saved %s files", {"%s"}, "XXXXX %s XXXXX"),
])
def test_xxxx_marks_words_and_keeps_icu(value, tokens, expected) -> None:
    assert pseudo_text(value, tokens, style="xxxx") == expected


def test_accent_style_keeps_icu_keywords() -> None:
    out = pseudo_text("{n, plural, one {# file} other {# files}}", {"n"})
    assert "{n, plural, one {" in out and "} other {" in out
    assert not re.search(r"\bfile\b", out)
