"""Normalizer: first line of a one-line answer, plural categories without # (ADR-137)."""

from __future__ import annotations

from llm_localizator.core.normalize import normalize_candidate
from llm_localizator.core.validate import glossary_answer


def test_first_line_kept_for_a_one_line_source() -> None:
    out, steps = normalize_candidate("Original: {path}", "Oryginał: {path}\n\n(original path)", "pl")
    assert (out, steps) == ("Oryginał: {path}", ["first_line"])
    multi, steps = normalize_candidate("Line one\nLine two", "Linia jeden\nLinia dwa", "pl")
    assert "first_line" not in steps and "\n" in multi


def test_plural_filled_only_without_a_number() -> None:
    src = "{n, plural, one {Skipped file: {names}.} other {Skipped files: {names}.}}"
    out, steps = normalize_candidate(src, "{n, plural, one {Pominięto plik: {names}.} "
                                          "other {Pominięto pliki: {names}.}}", "pl")
    assert steps == ["plural_fill"]
    assert "few {Pominięto pliki: {names}.}" in out and "many {Pominięto pliki: {names}.}" in out
    counted, steps = normalize_candidate("{n, plural, one {# file} other {# files}}",
                                         "{n, plural, one {# plik} other {# plików}}", "pl")
    assert steps == [] and "few" not in counted


def test_glossary_answer_skips_frames_with_placeholders() -> None:
    glossary = {"terms": {"run": {"pl": "przebieg"}}}
    assert glossary_answer("Run: {id}", glossary, "pl") is None
    assert glossary_answer("Run", glossary, "pl") == "Przebieg"


def test_a_broken_answer_is_not_cut() -> None:
    out, steps = normalize_candidate("Save changes", "Zapisz\nzmiany", "pl")
    assert "first_line" not in steps and out == "Zapisz\nzmiany"
    out, steps = normalize_candidate("Save changes", "Zapisz zmiany\nNote: imperative", "pl")
    assert out == "Zapisz zmiany" and "first_line" in steps
