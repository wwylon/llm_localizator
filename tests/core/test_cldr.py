"""Language reference helpers (the data itself is tested in test_locale_profiles.py)."""

from __future__ import annotations

from llm_localizator.core.cldr import known_locales, language_name, required_plural_categories


def test_language_name_known() -> None:
    assert language_name("pl") == "Polish"


def test_language_name_falls_back_to_code() -> None:
    assert language_name("zz") == "zz"


def test_language_name_uses_the_base_language_for_regions() -> None:
    assert language_name("pl-PL") == "Polish"
    assert language_name("pt-BR") == "Brazilian Portuguese"


def test_required_categories_default() -> None:
    assert required_plural_categories("zz") == {"one", "other"}


def test_arabic_requires_six_categories() -> None:
    assert required_plural_categories("ar") == {"zero", "one", "two", "few", "many", "other"}


def test_region_codes_inherit_the_language_plural_rules() -> None:
    assert required_plural_categories("pl-PL") == {"one", "few", "many", "other"}


def test_known_locales_lists_what_a_person_can_pick() -> None:
    codes = known_locales()
    assert codes[:2] == ["pl", "ar"]
    assert {"fr-CA", "pt-BR", "zh-TW", "en"} <= set(codes)
    assert "pt" not in codes
