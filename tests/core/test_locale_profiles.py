"""Language profiles: structure guards and per-language behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.core import locales
from llm_localizator.core.icu import extract_plural_categories
from llm_localizator.core.locale_ui import font_family, text_direction
from llm_localizator.core.locales import all_profiles, known_locales, profile
from llm_localizator.core.locales.base import CLDR_CATEGORIES, KNOWN_SCRIPTS
from llm_localizator.core.quality import check_number_format, check_suspicious_digraphs
from llm_localizator.core.scripts import SCRIPT_RANGES, expected_script
from llm_localizator.core.validate import (
    check_expansion_band,
    check_locale_typography,
    check_untranslated_fragments,
    validate_translation_detailed,
)
from llm_localizator.pipeline.prompts import BatchItem, build_batch_prompt

# Every locale the tool offered before profiles existed (old LOCALE_NAMES).
ORIGINAL_LOCALES = {
    "pl": "Polish", "ar": "Arabic", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "ru": "Russian", "nl": "Dutch", "sv": "Swedish",
    "pt-PT": "European Portuguese", "pt-BR": "Brazilian Portuguese",
    "zh": "Chinese (Simplified)", "ja": "Japanese", "he": "Hebrew", "tr": "Turkish",
    "da": "Danish", "nb": "Norwegian (Bokmal)", "fi": "Finnish", "is": "Icelandic",
    "id": "Indonesian", "bg": "Bulgarian", "hu": "Hungarian", "cs": "Czech",
    "el": "Greek", "th": "Thai", "vi": "Vietnamese", "ko": "Korean",
}


# ---- structure -------------------------------------------------------------

def test_every_original_locale_resolves_with_its_name() -> None:
    for code, name in ORIGINAL_LOCALES.items():
        assert profile(code).name == name, code
        assert profile(code).code == code


def test_original_display_order_is_kept() -> None:
    order = [c for c in known_locales() if c in ORIGINAL_LOCALES]
    assert order == list(ORIGINAL_LOCALES)


def test_no_code_is_defined_twice() -> None:
    codes = [p.code for p in all_profiles()]
    assert len(codes) == len(set(codes))


def test_every_module_in_the_package_is_registered() -> None:
    directory = Path(locales.__file__).parent
    on_disk = {
        path.stem.rstrip("_")
        for path in directory.glob("*.py")
        if path.stem not in ("__init__", "base")
    }
    registered = {name.rstrip("_") for name in locales._MODULE_NAMES}
    assert on_disk == registered


def test_known_scripts_match_the_script_tables() -> None:
    assert KNOWN_SCRIPTS == set(SCRIPT_RANGES)


@pytest.mark.parametrize("item", all_profiles(), ids=lambda p: p.code)
def test_profile_invariants(item) -> None:
    assert item.name
    assert item.script in KNOWN_SCRIPTS
    assert set(item.plural_categories) <= CLDR_CATEGORIES
    assert "other" in item.plural_categories
    if item.expansion_band:
        assert 0 < item.expansion_band[0] < item.expansion_band[1]
    if item.plural_example:
        found = extract_plural_categories(item.plural_example)
        assert found is not None, f"{item.code} example is not a valid ICU plural"
        assert set(item.plural_categories) <= found
    if item.decimal_mark is not None:
        assert item.decimal_mark in (",", ".")


@pytest.mark.parametrize(
    "check",
    [c for p in all_profiles() for c in p.typography_checks],
    ids=lambda c: c.id,
)
def test_every_typography_rule_fires_on_bad_and_not_on_good(check) -> None:
    assert check.fires(check.bad)
    assert not check.fires(check.good)


@pytest.mark.parametrize(
    "check",
    [c for p in all_profiles() for c in p.grammar_checks],
    ids=lambda c: c.id,
)
def test_every_grammar_rule_fires_on_bad_and_not_on_good(check) -> None:
    assert check.fires(check.bad)
    assert not check.fires(check.good)


def test_grammar_examples_pass_their_own_language_checks() -> None:
    """A vetted example must never trip the heuristics it is meant to teach."""
    for prof in all_profiles():
        for _src, dst in prof.grammar_examples:
            assert not [c.id for c in prof.grammar_checks if c.fires(dst)], (prof.code, dst)


@pytest.mark.parametrize("text", [
    "22 pliki", "2 pliki", "Dwóch graczy", "5 plików", "Pobrano 12 obrazów", "Dwa razy",
    "trzy karty", "Cztery kolory",
])
def test_polish_grammar_checks_stay_quiet_on_correct_text(text) -> None:
    from llm_localizator.core.validate import check_locale_grammar

    assert check_locale_grammar(text, "pl") is None


@pytest.mark.parametrize("text", ["Dwa gracze", "2 użytkownicy", "5 pliki", "12 lewy", "25 modele"])
def test_polish_grammar_checks_catch_agreement_errors(text) -> None:
    from llm_localizator.core.validate import check_locale_grammar

    assert check_locale_grammar(text, "pl")


def test_grammar_rules_reach_translate_and_judge_prompts() -> None:
    from llm_localizator.pipeline.judge import build_judge_prompt
    from llm_localizator.pipeline.prompts import grammar_block

    block = grammar_block("pl")
    assert "dwóch graczy" in block and "Lewy obrońców" in block
    judge = build_judge_prompt(
        source="Two players", translated="Dwa gracze", language="Polish",
        domain="a game", locale="pl",
    )
    assert "grammar_error" in judge and "dwóch graczy" in judge
    assert grammar_block("xx-unknown") == "" or "Grammar" not in grammar_block("en")


# ---- lookup ----------------------------------------------------------------

@pytest.mark.parametrize(
    "locale, code",
    [
        ("pl-PL", "pl"), ("PL", "pl"), ("fr-CA", "fr-CA"), ("fr-BE", "fr"), ("fr_CA", "fr-CA"),
        ("pt-br", "pt-BR"), ("pt-AO", "pt"), ("zh-CN", "zh"), ("zh-Hant-HK", "zh-TW"),
        ("de-CH", "de-CH"), ("de-AT", "de"), ("en-GB", "en"),
    ],
)
def test_lookup_falls_back_from_region_to_language(locale, code) -> None:
    assert profile(locale).code == code


def test_unknown_locale_gets_a_harmless_default() -> None:
    unknown = profile("zz")
    assert unknown.name == "" and unknown.plural_categories == ("one", "other")
    assert profile(None).code == "" and profile("").code == ""


def test_a_bare_portuguese_code_is_not_offered() -> None:
    assert "pt" not in known_locales()
    assert {"pt-PT", "pt-BR"} <= set(known_locales())


# ---- data carried over from the old scattered tables ----------------------

def test_carried_over_data_spot_checks() -> None:
    assert profile("ar").plural_categories == ("zero", "one", "two", "few", "many", "other")
    assert profile("pl").expansion_band == (1.10, 1.50)
    assert profile("pl").gettext_plural_forms.startswith("nplurals=3")
    assert profile("pt-BR").gettext_plural_forms == "nplurals=2; plural=(n > 1);"
    assert profile("pt-PT").gettext_plural_forms == "nplurals=2; plural=(n != 1);"
    assert profile("nl").hyphenate and profile("de").hyphenate and not profile("fr").hyphenate
    assert not profile("th").segmented and not profile("ja").segmented
    assert profile("fr").segmented
    assert profile("ru").script == "cyrillic" and profile("hi").script == "devanagari"
    assert expected_script("ko") == "cjk" and expected_script("xx") == "latin"
    assert profile("pl").decimal_mark == "," and profile("en").decimal_mark == "."
    assert profile("ja").decimal_mark is None


@pytest.mark.parametrize("code", ["ar", "he", "fa", "ur", "yi", "ps", "sd", "ug", "ckb", "dv"])

def test_right_to_left_languages(code) -> None:
    assert profile(code).direction == "rtl"
    assert text_direction(code) == "rtl"


def test_left_to_right_by_default() -> None:
    assert text_direction("pl") == "ltr" and text_direction("zz") == "ltr"


def test_font_follows_the_script() -> None:
    assert "Arabic" in font_family("ar-EG")
    assert "Thai" in font_family("th")
    assert font_family("el") == font_family("pl")  # no dedicated stack


def test_digraph_check_uses_the_profile() -> None:
    assert check_suspicious_digraphs("zaąęx", "pl") is not None
    assert check_suspicious_digraphs("hello", "pl") is None
    assert check_suspicious_digraphs("äöx", "de-CH") is not None


def test_number_format_uses_the_profile_decimal_mark() -> None:
    assert check_number_format("Costs 1,234.5", "Kosztuje 1.234,5", "pl") is None
    assert check_number_format("Costs 1,234.5", "Kostet 1,234.5", "de") is not None
    # Swiss German uses a decimal point, unlike German.
    assert check_number_format("Costs 1,234.5", "Kostet 1,234.5", "de-CH") is None
    assert check_number_format("1,234.5", "1,234.5", "ja") is None


def test_expansion_band_comes_from_the_profile() -> None:
    assert check_expansion_band("Start the game now", "x" * 90, "pl") is not None
    assert check_expansion_band("Start the game now", "x" * 90, "zz") is None


# ---- V33: English leftovers ------------------------------------------------

@pytest.mark.parametrize(
    "locale, text",
    [
        ("it", "Vai a casa e apri la porta in fretta"),
        ("es", "Ve a casa a las cinco"),
        ("pl", "A to jest to, a nie tamto"),
        ("nl", "Is het in orde of niet, het was goed"),
        ("de", "Was ist in dem Haus, das an der Ecke steht"),
        ("fr", "Il a un an de plus"),
        ("da", "Det er for meget, og to er nok"),
        ("vi", "Tôi to an in"),
    ],
)
def test_v33_ignores_words_that_are_ordinary_in_the_language(locale, text) -> None:
    assert check_untranslated_fragments(text, locale) is None


def test_v33_still_catches_real_english_leftovers() -> None:
    assert check_untranslated_fragments("Enregistrez the document and save", "fr") is not None
    assert check_untranslated_fragments("Vai a casa the door and this", "it") is not None
    assert check_untranslated_fragments("The file and the folder", "en") is None


# ---- V34: typography per language -----------------------------------------

@pytest.mark.parametrize(
    "locale, text, fires",
    [
        ("fr", "Erreur: fichier", True),
        ("fr", "Erreur : fichier", False),
        ("fr", "Il est 10:30 ici", False),
        ("fr", "Voir https://exemple.fr/page?id=1", False),
        ("fr", "Vraiment?", True),
        ("fr-CA", "Erreur: fichier", True),
        ("fr-CA", "Vraiment?", False),
        ("fr-CA", "Erreur : fichier", False),
        ("es", "Guardar cambios?", True),
        ("es", "¿Guardar cambios?", False),
        ("es", "¡Listo!", False),
        ("es", "Listo!", True),
        ("es", "Abre https://ejemplo.es/a?b=1", False),
        ("el", "Θέλετε να αποθηκεύσετε?", True),
        ("el", "Θέλετε να αποθηκεύσετε;", False),
        ("ar", "هل تريد الحفظ?", True),
        ("ar", "هل تريد الحفظ؟", False),
        ("ar", "السعر ١٬٠٠٠,٠٠", False),
        ("zh", "你好,世界", True),
        ("zh", "你好，世界。", False),
        ("zh", "打开设置.json文件", False),
        ("ja", "こんにちは,世界.", True),
        ("ja", "こんにちは、世界。", False),
        ("th", "สวัสดี ครับ ขอบคุณ", False),
        ("de-CH", "Straße", True),
        ("de-CH", "Strasse", False),
        ("de", "Straße", False),
        ("pl", "Anything: goes", False),
    ],
)
def test_v34_per_language(locale, text, fires) -> None:
    assert (check_locale_typography(text, locale) is not None) is fires


def test_v34_reaches_the_detailed_validator() -> None:
    _ok, warnings = validate_translation_detailed("Save?", "Guardar?", "es", {})
    assert any(w.id == "V34" for w in warnings)


# ---- prompts read the profile ---------------------------------------------

def _prompt(locale: str, language: str) -> str:
    return build_batch_prompt([BatchItem(source="Save", message_key="a.b")], language, locale, "app", "")


def test_simplified_chinese_prompt_uses_curly_quotes_not_corner_brackets() -> None:
    text = _prompt("zh", "Chinese (Simplified)")
    assert "“ ”" in text and "「" not in text


def test_traditional_chinese_prompt_uses_corner_brackets() -> None:
    assert "「 」" in _prompt("zh-TW", "Chinese (Traditional)")


def test_french_prompt_mentions_non_breaking_space_and_canada_differs() -> None:
    assert "non-breaking space" in _prompt("fr", "French")
    assert "Do NOT put a space before" in _prompt("fr-CA", "French (Canada)")


def test_language_without_rules_adds_no_typography_line() -> None:
    assert "Typography for" not in _prompt("it", "Italian")
    assert "Typography for" not in _prompt("zz", "Zzish")


def test_regional_code_gets_the_language_guidance() -> None:
    assert "Typography for fr-BE" in _prompt("fr-BE", "French")


def test_script_and_direction_corrections() -> None:
    assert profile("dv").script == "thaana" and expected_script("dv") == "thaana"
    assert profile("ku").direction == "ltr" and profile("ku").script == "latin"
    assert profile("ckb").direction == "rtl" and profile("ckb").script == "arabic"
