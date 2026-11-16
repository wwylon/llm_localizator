"""C-003: profile formality wording and the V40 advisory check."""

from __future__ import annotations

import pytest

from llm_localizator.core.locales import profile
from llm_localizator.core.validate import check_register


@pytest.mark.parametrize("locale", ["de", "fr", "pl"])
def test_markers_exist_and_wording_set(locale):
    p = profile(locale)
    assert p.informal_prompt and p.formal_prompt
    assert p.informal_marker and p.formal_marker


@pytest.mark.parametrize(
    "locale,register,good,bad",
    [
        ("de", "formal", "Speichern Sie die Datei, wenn Sie fertig sind", "Speichere dich, wenn du fertig bist"),
        ("de", "informal", "Speichere die Datei, wenn du fertig bist", "Bitte sagen, dass Sie fertig sind"),
        ("fr", "formal", "Enregistrez votre fichier", "Enregistre ton fichier"),
        ("fr", "informal", "Enregistre ton fichier", "Enregistrez votre fichier"),
        ("pl", "informal", "Zapisz swój plik, ty", "Czy Pan jest pewien"),
        ("pl", "formal", "Czy Pan jest pewien", "Zapisz plik, ty"),
    ],
)
def test_check_register(locale, register, good, bad):
    assert check_register(good, locale, register) is None
    assert check_register(bad, locale, register)


def test_unprofiled_language_is_skipped():
    assert check_register("anything", "ja", "formal") is None


def test_sentence_initial_german_sie_is_not_flagged_as_formal():
    # "Sie" opening a sentence is ambiguous (they / she), so informal text stays clean.
    assert check_register("Sie speichern die Datei", "de", "informal") is None


def test_style_for_adds_wording_only_when_explicit(tmp_path):
    from llm_localizator.projects.config import load_config

    base = (
        "[project]\nname = 'demo'\nsource_locale = 'en'\n\n"
        "[catalog]\nformat = 'json-nested'\npath = 'messages/{locale}/{namespace}.json'\n\n"
        "[locales]\ntargets = ['de']\n\n[provider]\nkind = 'null'\n"
    )
    plain = tmp_path / "a.toml"
    plain.write_text(base, encoding="utf-8")
    explicit = tmp_path / "b.toml"
    explicit.write_text(base + "\n[prompt]\nregister = 'formal'\n", encoding="utf-8")
    _, n_plain = load_config(plain).style_for("de")
    reg, n_explicit = load_config(explicit).style_for("de")
    assert "Sie" not in n_plain
    assert reg == "formal" and "Sie" in n_explicit
