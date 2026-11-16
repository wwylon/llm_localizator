"""Soft-hyphen post-processing.

pyphen is an optional dependency, so every test here must pass both with and
without it installed. The no-op path is the contract we actually rely on.
"""

from __future__ import annotations

from llm_localizator.core.hyphens import SOFT_HYPHEN, apply_soft_hyphens, pyphen_available


def test_non_hyphenating_locale_is_untouched() -> None:
    text = "Bardzo długie słowo kluczowe"
    assert apply_soft_hyphens(text, "pl") == text


def test_short_tokens_are_untouched() -> None:
    assert apply_soft_hyphens("Kurz und gut", "de") == "Kurz und gut"


def test_hyphenation_is_a_noop_without_pyphen() -> None:
    text = "Reihenfolgenbestimmung"
    result = apply_soft_hyphens(text, "de")
    if pyphen_available():
        assert SOFT_HYPHEN in result
        assert result.replace(SOFT_HYPHEN, "") == text
    else:
        assert result == text


def test_content_is_never_altered() -> None:
    """Whatever happens, stripping soft hyphens must recover the original."""
    for text in ["Reihenfolgenbestimmung", "Ein sehr langes Kompositum hier", ""]:
        assert apply_soft_hyphens(text, "de").replace(SOFT_HYPHEN, "") == text


def test_whitespace_is_preserved() -> None:
    text = "Wort   mit    Abstand"
    assert apply_soft_hyphens(text, "de").replace(SOFT_HYPHEN, "") == text
