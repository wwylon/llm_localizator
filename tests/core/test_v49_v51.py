"""V49 description leak, V50 invented markup, V51 leading symbol (ADR-130)."""

from __future__ import annotations

from llm_localizator.core.normalize import normalize_candidate
from llm_localizator.core.validate import (
    check_domain_leak, check_invented_markup, check_leading_symbol, classify_failure, validate_translation,
)

DOMAIN = "a card-game arena web app where people play trick-taking games (euchre, whist, spades) against bots"


def test_v49_description_leak() -> None:
    assert check_domain_leak("bags N–S {ns} / E–W {ew}",
                             "Nadróbki N-S {ns} / Graj w euchre lub whist przeciwko botom! {ew}", DOMAIN)
    assert check_domain_leak("Euchre rate", "Odsetek Euchre", DOMAIN) is None
    assert check_domain_leak("Play euchre or whist", "Graj w euchre lub whist", DOMAIN) is None
    assert check_domain_leak("x", "euchre whist", None) is None


def test_v50_invented_markup() -> None:
    assert check_invented_markup("{seat} may announce", "Może ogłosić **{seat}**")
    assert check_invented_markup("Use **bold**", "Użyj **pogrubienia**") is None
    icu = "{n, plural, one {Download all (# file)} other {Download all (# files)}}"
    assert check_invented_markup(icu, "Pobierz wszystkie {n, plural, one {# plik} other {# plików}}")
    assert check_invented_markup(icu, "{n, plural, one {Pobierz (# plik)} other {Pobierz (# plików)}}") is None


def test_v51_leading_symbol_and_restore() -> None:
    assert check_leading_symbol("~{t} on {dev}", "Około {t} na {dev}")
    assert check_leading_symbol("~{t} on {dev}", "~{t} na {dev}") is None
    text, steps = normalize_candidate("~{t} on {dev}", "Około {t} na {dev}", "pl")
    assert text == "~{t} na {dev}" and "symbol" in steps


def test_gate_and_classification() -> None:
    ok, reason = validate_translation("{seat} may announce", "Może ogłosić **{seat}**", "pl", {})
    assert not ok and classify_failure(reason) == "V50"
    ok, reason = validate_translation("bags {ns}", "Torby {ns} euchre whist", "pl", {}, prompt_text=DOMAIN)
    assert not ok and classify_failure(reason) == "V49"
