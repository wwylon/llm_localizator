"""Deterministic output clean-up (plan Part C, C2 / E6, E9)."""

from __future__ import annotations

import pytest

from llm_localizator.core.normalize import normalize_candidate
from llm_localizator.pipeline.candidates import validate_candidate


@pytest.mark.parametrize(
    ("source", "out", "want", "steps"),
    [
        ("Save changes", "„Zapisz zmiany”", "Zapisz zmiany", ["quotes"]),
        ("Save changes", '"Zapisz zmiany"', "Zapisz zmiany", ["quotes"]),
        ("Save changes", "«Zapisz»", "Zapisz", ["quotes"]),
        ('"Quoted" source', '"Cytowane" źródło', '"Cytowane" źródło', []),
        ("Open or close", '"Otwórz" lub "Zamknij"', '"Otwórz" lub "Zamknij"', []),
        ("Loading…", "Ładowanie...", "Ładowanie…", ["ellipsis"]),
        ("Loading...", "Ładowanie...", "Ładowanie...", []),
        ("Settings", "ustawienia", "Ustawienia", ["case"]),
        ("and {n} more", "I {n} więcej", "i {n} więcej", ["case"]),
        ("seed", "URL", "URL", []),
        ("{n} files", "{n} plików", "{n} plików", []),
    ],
)
def test_normalize_polish(source, out, want, steps) -> None:
    assert normalize_candidate(source, out, "pl") == (want, steps)


def test_quotes_inside_icu_branches_are_stripped() -> None:
    src = "{n, plural, one {# file} other {# files}}"
    out = '{n, plural, one {„# plik”} few {"# pliki"} many {# plików} other {# pliku}}'
    text, steps = normalize_candidate(src, out, "pl")
    assert text == "{n, plural, one {# plik} few {# pliki} many {# plików} other {# pliku}}"
    assert steps == ["icu_quotes"]


def test_german_nouns_keep_their_capital() -> None:
    assert normalize_candidate("settings", "Einstellungen", "de") == ("Einstellungen", [])


def test_turkish_dotted_capital() -> None:
    assert normalize_candidate("Settings", "ilk", "tr")[0] == "İlk"


def test_candidate_gate_accepts_quoted_model_output() -> None:
    applied: list[str] = []
    text, reason = validate_candidate("Save changes", "„zapisz zmiany”", "pl", {}, applied=applied)
    assert reason is None and text == "Zapisz zmiany"
    assert applied == ["quotes", "case"]
