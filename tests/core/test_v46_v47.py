"""V46 prompt leak and V47 ICU structure (plan Part C, C2). Cases are real catalogue defects."""

from __future__ import annotations

import pytest

from llm_localizator.core.validate import (
    check_icu_structure,
    check_prompt_leak,
    classify_failure,
    validate_translation,
)


@pytest.mark.parametrize(
    ("source", "out"),
    [
        ("~{lo}–{hi} on {dev}", "~{lo}–{hi} Wybierz obraz, wybierz model i skalę, zobacz podgląd {dev}"),
        ("Ramsch", "Ramsch to nieudany kontrakt, który daje obrońcom wszystkie punkty."),
        ("H{n}", "„Twoja historiaowa ręka: H{n}”"),
        ("Archive", "Archiwum  [klucz: admin.archive]  [kontekst: używane w AdminClubs]"),
    ],
)
def test_prompt_leak_is_rejected(source, out) -> None:
    ok, reason = validate_translation(source, out, "pl", {})
    assert not ok and classify_failure(reason) in {"V46", "V43"}, reason
    assert check_prompt_leak(source, out)


@pytest.mark.parametrize(
    ("source", "out"),
    [
        ("Save changes", "Zapisz zmiany"),
        ("{rank} of {suit}", "{rank} {suit}"),
        ("Settings", "Einstellungen"),
        ("Pick an image, choose a model and press the button to start.",
         "Wybierz obraz, wybierz model i naciśnij przycisk, aby rozpocząć."),
        ("{n, plural, one {# file} other {# files}}",
         "{n, plural, one {# plik} few {# pliki} many {# plików} other {# pliku}}"),
    ],
)
def test_normal_translations_pass(source, out) -> None:
    assert check_prompt_leak(source, out) is None
    assert check_icu_structure(source, out) is None


def test_select_turned_into_plural_is_rejected() -> None:
    src = "{won, select, yes {You won} other {You lost}}"
    ok, reason = validate_translation(src, "{won, plural, one {Wygrałeś} other {Przegrałeś}}", "pl", {})
    assert not ok and classify_failure(reason) == "V47", reason


def test_select_branch_keys_must_match() -> None:
    src = "{who, select, you {You won} bot {Bot won} other {They won}}"
    reason = check_icu_structure(src, "{who, select, you {Wygrałeś} other {Wygrali}}")
    assert reason and "bot" in reason
    assert check_icu_structure(src, "{who, select, you {Wygrałeś} bot {Bot wygrał} other {Wygrali}}") is None


def test_dropped_plural_is_rejected() -> None:
    reason = check_icu_structure("{n, plural, one {# penalty pt} other {# penalty pts}}", "{n} penalty pts")
    assert reason and "none" in reason
