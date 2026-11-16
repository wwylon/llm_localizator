"""V13 approved-term matching: case, harakat, Arabic prefixes and plurals, Polish endings,
and source-side words that are not the term (placeholders, hyphenated compounds)."""

from __future__ import annotations

import pytest

from llm_localizator.core.validate import _contains_morphological, glossary_violations


@pytest.mark.parametrize("text,term,locale", [
    ("Stół brydżowy", "stół", "pl"),            # capital letter
    ("Dołącz do stołu", "stół", "pl"),          # ó -> o and ending
    ("Nie można połączyć się ze stołem.", "stół", "pl"),
    ("liczba lew", "lewa", "pl"),                # final vowel changes
    ("Lewy 3 z 13", "lewa", "pl"),
    ("أبحث عن شريك.", "الشريك", "ar"),           # article dropped
    ("ادعُ شريكاً", "الشريك", "ar"),
    ("التوزيعات", "التوزيعة", "ar"),             # ta marbuta plural
    ("لوحات التوزيع", "التوزيعة", "ar"),
    ("ببطولات مرنة", "بطولة", "ar"),             # preposition + plural
    ("المعلن", "المُعلن", "ar"),                 # harakat differ
])
def test_inflected_forms_of_the_approved_term_match(text: str, term: str, locale: str) -> None:
    assert _contains_morphological(text, term, locale)


@pytest.mark.parametrize("text,term,locale", [
    ("Stopy i stodoły", "stół", "pl"),           # unrelated words sharing letters
    ("Aukcja jeszcze się nie rozpoczęła.", "licytacja", "pl"),
    ("لوحة اللعب", "التوزيعة", "ar"),            # a different word for board
    ("Board", "التوزيعة", "ar"),
])
def test_other_words_do_not_match(text: str, term: str, locale: str) -> None:
    assert not _contains_morphological(text, term, locale)


def _glossary():
    return {"terms": {
        "bid": {"pl": "zapowiedź"}, "dummy": {"pl": "dziadek"}, "table": {"pl": "stół"},
    }}


def test_placeholder_names_and_hyphenated_compounds_are_not_the_term() -> None:
    assert glossary_violations("{bid} · {pct}% make", "{bid} · {pct}% wykonania", _glossary(), "pl") == []
    assert glossary_violations("Double-dummy checked", "Sprawdzone analizą double-dummy", _glossary(), "pl") == []


def test_a_real_miss_is_still_reported_and_stays_advisory() -> None:
    issues = glossary_violations("Bridge table", "Open table", _glossary(), "pl")
    assert [i.kind for i in issues] == ["missing-approved"]
    assert not issues[0].blocking
