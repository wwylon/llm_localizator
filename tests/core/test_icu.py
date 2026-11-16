"""ICU placeholder and plural-category extraction.

Ported from bridge's ``scripts/test_localize_messages.py``
(TestPlaceholderExtraction, TestPluralCategoryExtraction). The Arabic
single-word-branch case is the regression that motivates the brace-depth parser.
"""

from __future__ import annotations

import pytest

from llm_localizator.core.icu import (
    extract_placeholders,
    extract_plural_categories,
    satisfied_categories,
    top_level_brace_spans,
)


# ---- placeholders ----------------------------------------------------------

def test_simple_placeholder() -> None:
    assert extract_placeholders("Hello {name}") == {"name"}


def test_multiple_placeholders() -> None:
    assert extract_placeholders("{done} of {total} complete") == {"done", "total"}


def test_no_placeholders() -> None:
    assert extract_placeholders("Just plain text") == set()


def test_plural_clause_extracts_only_the_driving_variable() -> None:
    s = "{n, plural, one {# trick} other {# tricks}}"
    assert extract_placeholders(s) == {"n"}


def test_arabic_single_word_plural_branch_not_mistaken_for_placeholder() -> None:
    """The regression the brace-depth parser exists for.

    ``two {عضوان}`` is one Unicode token with no spaces, so a flat ``\\{(\\w+)\\}``
    scan reads it as a placeholder named "عضوان".
    """
    s = "{n, plural, zero {# عضو} one {عضو واحد} two {عضوان} few {# أعضاء} many {# عضوا} other {# عضو}}"
    assert extract_placeholders(s) == {"n"}


def test_plural_embedded_mid_sentence_not_at_string_end() -> None:
    s = "You have {n, plural, one {# message} other {# messages}} waiting"
    assert extract_placeholders(s) == {"n"}


def test_placeholder_alongside_plural_clause() -> None:
    s = "{name} won {n, plural, one {# trick} other {# tricks}}"
    assert extract_placeholders(s) == {"name", "n"}


def test_select_clause_extracts_driving_variable() -> None:
    s = "{gender, select, male {He} female {She} other {They}} bid"
    assert extract_placeholders(s) == {"gender"}


def test_non_identifier_brace_content_is_not_a_placeholder() -> None:
    # A brace span whose inner text is not a bare identifier contributes nothing.
    assert extract_placeholders("literal { not an ident } here") == set()


# ---- brace spans -----------------------------------------------------------

def test_top_level_spans_honour_nesting() -> None:
    s = "a {x} b {n, plural, one {# y} other {# z}} c"
    assert top_level_brace_spans(s) == ["{x}", "{n, plural, one {# y} other {# z}}"]


def test_unbalanced_braces_do_not_raise() -> None:
    assert top_level_brace_spans("{unclosed") == []


# ---- plural categories -----------------------------------------------------

def test_not_a_plural_string_returns_none() -> None:
    assert extract_plural_categories("Hello {name}") is None


def test_english_categories() -> None:
    s = "{n, plural, one {# trick} other {# tricks}}"
    assert extract_plural_categories(s) == {"one", "other"}
    glued = "{n, plural, otherX {nope} other {# tricks}}"
    assert extract_plural_categories(glued) == {"other"}


def test_polish_categories() -> None:
    s = "{n, plural, one {# punkt} few {# punkty} many {# punktów} other {# punktu}}"
    assert extract_plural_categories(s) == {"one", "few", "many", "other"}


def test_arabic_all_six_categories() -> None:
    s = (
        "{n, plural, zero {# نقطة} one {نقطة واحدة} two {نقطتان} "
        "few {# نقاط} many {# نقطة} other {# نقطة}}"
    )
    assert extract_plural_categories(s) == {"zero", "one", "two", "few", "many", "other"}


@pytest.mark.parametrize("s", ["", "no braces", "{plain}"])
def test_non_plural_inputs(s: str) -> None:
    assert extract_plural_categories(s) is None


def test_explicit_value_selectors_are_captured() -> None:
    s = "{n, plural, =0 {No one going yet} one {# going} other {# going}}"
    assert extract_plural_categories(s) == {"=0", "one", "other"}


def test_selectordinal_categories_are_extracted() -> None:
    s = "Take the {n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}} turn"
    assert extract_plural_categories(s) == {"one", "two", "few", "other"}


def test_satisfied_categories_expands_explicit_selectors() -> None:
    assert satisfied_categories({"=0", "one", "other"}) == {"=0", "zero", "one", "other"}
    assert satisfied_categories({"=1", "other"}) == {"=1", "one", "other"}


def test_satisfied_categories_is_identity_without_explicit_selectors() -> None:
    assert satisfied_categories({"one", "other"}) == {"one", "other"}


def test_explicit_selector_does_not_become_a_placeholder() -> None:
    s = "{n, plural, =0 {No one going yet} one {# going} other {# going}}"
    assert extract_placeholders(s) == {"n"}


def test_nested_plural_categories_do_not_satisfy_the_outer_one() -> None:
    from llm_localizator.core.icu import extract_plural_categories

    text = "{n, plural, other {{m, plural, one {a} few {b} other {c}}}}"
    assert extract_plural_categories(text) == {"other"}
