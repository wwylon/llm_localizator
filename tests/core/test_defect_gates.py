"""V39, the shared failure classifier, plural endings for non-inflecting locales, soft issues."""

from __future__ import annotations

import pytest

from llm_localizator.core.script_checks import latin_leftover_issues
from llm_localizator.core.validate import (
    _contains_morphological,
    classify_failure,
    validate_translation,
    validate_translation_detailed,
)
from llm_localizator.pipeline.candidates import soft_issues


def test_a_backslash_the_source_lacks_is_rejected() -> None:
    ok, reason = validate_translation("Hello world", "Witaj\\", "pl", {})
    assert not ok and "backslash" in reason
    assert classify_failure(reason) == "V39"
    assert validate_translation_detailed("Hello world", "Witaj\\", "pl", {})[1][0].id == "V39"


def test_a_backslash_the_source_has_is_fine() -> None:
    assert validate_translation("Path C:\\temp", "Sciezka C:\\temp", "pl", {})[0]


@pytest.mark.parametrize("reason,code", [
    ("missing placeholders ['{n}']", "V02"),
    ("missing required plural categories for pl: ['few']", "V03"),
    ("forbidden variant 'x' used for glossary term 'y'", "V04"),
    ("HTML tag mismatch: missing ['b']", "V27"),
    ("literal(s) missing from translation: https://x", "V32"),
    ("empty or whitespace-only translation", "V05"),
])
def test_one_id_per_failure_everywhere(reason: str, code: str) -> None:
    assert classify_failure(reason) == code


@pytest.mark.parametrize("text,term,locale", [
    ("Gewonnene Stiche: 3", "Stich", "de"),
    ("Keine offenen Tische", "Tisch", "de"),
    ("Kommende Turniere", "Turnier", "de"),
    ("Plis gagnés", "pli", "fr"),
    ("Tournois à venir", "tournoi", "fr"),
])
def test_regular_plurals_match_in_locales_without_rich_inflection(text, term, locale) -> None:
    assert _contains_morphological(text, term, locale)


def test_a_different_word_does_not_match_the_term() -> None:
    assert not _contains_morphological("Tischtennis spielen", "Tisch", "de")
    assert not _contains_morphological("Blick", "Stich", "de")


def test_latin_leftover_ignores_a_wholly_untranslated_string() -> None:
    assert latin_leftover_issues("Make your bid", "Make your bid", "ar") == []
    assert latin_leftover_issues("Sign in", "Access تسجيل الدخول", "ar")
    assert latin_leftover_issues("Sign in", "Zaloguj się Access", "pl") == []  # Latin locale


def test_soft_issues_names_each_advisory_defect() -> None:
    glossary = {"terms": {"table": {"pl": "stół"}}}
    assert soft_issues("Join table", "Dołącz do stołu", "pl", glossary) == []
    assert soft_issues("Sign in", "Access تسجيل الدخول", "ar", {})
    assert soft_issues("Make your bid", "Make your bid", "pl", {}) == ["identical to the source: translate it"]
    assert any("approved term" in i for i in soft_issues("Join table", "Dołącz do gry", "pl", glossary))
    assert soft_issues("Save", "Save", "pl", {}) == []  # a single word may be intentional
