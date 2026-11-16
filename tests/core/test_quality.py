"""Automated quality scoring and batch-bleed guards."""

from __future__ import annotations

from llm_localizator.core.quality import (
    check_empty_translation,
    check_unexpected_script,
    check_whitespace_parity,
    expected_script,
    score_translation,
    script_prompt_rule,
    token_overlap,
)
from llm_localizator.pipeline.translate import reject_duplicate_batch_outputs


def test_reject_duplicate_batch_outputs_nulls_bleed() -> None:
    sources = ["saved", "rejected", "locale code is required"]
    results = [
        "Wymagana jest kod lokalizacji",
        "Wymagana jest kod lokalizacji",  # bleed from error string
        "Wymagana jest kod lokalizacji",
    ]
    out = reject_duplicate_batch_outputs(sources, results)
    assert out[0] == "Wymagana jest kod lokalizacji"
    assert out[1] is None
    assert out[2] is None


def test_reject_duplicate_allows_short_strings_from_different_sources() -> None:
    sources = ["ok_button", "no_button"]
    results = ["OK", "OK"]
    assert reject_duplicate_batch_outputs(sources, results) == ["OK", "OK"]
    sources = ["OK", "OK"]
    results = ["OK", "OK"]
    assert reject_duplicate_batch_outputs(sources, results) == ["OK", "OK"]


def test_token_overlap_identical() -> None:
    assert token_overlap("hello world", "hello world") == 1.0


def test_token_overlap_disjoint() -> None:
    assert token_overlap("alpha beta", "gamma delta") == 0.0


def test_token_overlap_strips_env_var_identifiers() -> None:
    """SCREAMING_SNAKE must not split into bridge/super/admin/emails."""
    src = (
        "Sign in with a staff account. Super-admins are configured via "
        "BRIDGE_SUPER_ADMIN_EMAILS."
    )
    back = (
        "Sign in with a staff account. Super-admins are configured via "
        "BRIDGE_SUPER_ADMIN_EMAILS."
    )
    assert token_overlap(src, back) == 1.0
    # Env-only difference must not move the needle — prose matches.
    back_other_env = (
        "Sign in with a staff account. Super-admins are configured via "
        "OTHER_CONFIG_FLAG."
    )
    assert token_overlap(src, back_other_env) == 1.0
    # Without stripping, underscore-split tokens would appear in the set.
    from llm_localizator.core.quality import TOKEN_RE, strip_screaming_snake

    stripped = strip_screaming_snake(src)
    assert "BRIDGE_SUPER_ADMIN_EMAILS" not in stripped
    assert "emails" not in {t.lower() for t in TOKEN_RE.findall(stripped)}


def test_empty_translation() -> None:
    assert check_empty_translation("  ") is not None
    assert check_empty_translation("ok") is None


def test_unexpected_script_arabic_with_cjk() -> None:
    msg = check_unexpected_script("الキー", "ar")
    assert msg is not None
    assert "cjk" in msg


def test_unexpected_script_polish_with_cjk() -> None:
    msg = check_unexpected_script("nie翻譯", "pl")
    assert msg is not None
    assert "cjk" in msg


def test_expected_script_matrix() -> None:
    assert expected_script("zh") == "cjk"
    assert expected_script("ja-JP") == "cjk"
    assert expected_script("ko") == "cjk"
    assert expected_script("el") == "greek"
    assert expected_script("th") == "thai"
    assert expected_script("ar") == "arabic"
    assert expected_script("hi") == "devanagari"
    assert expected_script("pl") == "latin"


def test_script_prompt_and_validator_agree_on_cjk() -> None:
    rule = script_prompt_rule("zh", "Chinese")
    assert "CJK" in rule
    assert "Cyrillic" in rule
    assert check_unexpected_script("保存", "zh") is None
    assert check_unexpected_script("保存ключ", "zh") is not None


def test_script_prompt_and_validator_agree_on_thai() -> None:
    rule = script_prompt_rule("th", "Thai")
    assert "Thai" in rule
    assert "CJK" in rule
    assert check_unexpected_script("บันทึก", "th") is None
    assert check_unexpected_script("บันทึก翻訳", "th") is not None


def test_script_prompt_and_validator_agree_on_arabic() -> None:
    rule = script_prompt_rule("ar", "Arabic")
    assert "Arabic" in rule
    assert check_unexpected_script("حفظ", "ar") is None
    assert check_unexpected_script("حفظキー", "ar") is not None


def test_score_identical_english_penalty() -> None:
    result = score_translation(
        "Add & queue a translate job",
        "Add & queue a translate job",
        "pl",
    )
    assert result.score < 0.55


def test_score_good_enough_polish() -> None:
    result = score_translation("Cancel", "Anuluj", "pl")
    assert result.score >= 0.55


def test_short_label_bt_overlap_is_advisory_only() -> None:
    result = score_translation(
        "untranslated",
        "bez tłumaczenia",
        "pl",
        back_translated="without translation",
    )
    assert result.score >= 0.55
    assert any("overlap" in s for s in result.signals)


def test_long_source_still_penalized_on_low_bt_overlap() -> None:
    result = score_translation(
        "Add a new locale and queue translation",
        "Dodaj nową lokalizację",
        "pl",
        back_translated="completely unrelated text here",
    )
    assert result.score < 0.55


def test_validate_rejects_empty() -> None:
    from llm_localizator.core.validate import validate_translation

    ok, reason = validate_translation("Hello", "  ", "pl", {})
    assert not ok
    assert "empty" in reason


def test_whitespace_parity() -> None:
    assert check_whitespace_parity("Hello", "Hello") is None
    assert check_whitespace_parity(" Hello", "Hello") is not None


def test_number_format_flags_a_kept_english_decimal_in_german() -> None:
    from llm_localizator.core.quality import check_number_format

    assert check_number_format("Total 1,234.56", "Summe 1,234.56", "de")
    assert check_number_format("Total 1,234.56", "Summe 1.234,56", "de") is None
    assert check_number_format("Total 1,234.56", "Summe 9.999,99", "de") is None
    assert check_number_format("On 01/02/2026", "Am 02/01/2026", "de")
    assert check_number_format("On 01/02/2026", "Am 01.02.2026", "de") is None


# --- dimensions: every score explains itself -------------------------------------------------

def test_bt_score_carries_all_deterministic_dimensions() -> None:
    result = score_translation(
        "Save your changes", "Zapisz swoje zmiany", "pl",
        back_translated="Save your changes", max_chars=40,
    )
    assert result.dimensions == {
        "placeholder_ok": 1.0, "glossary_ok": 1.0, "script_ok": 1.0,
        "length_ok": 1.0, "bt_overlap": 1.0,
    }


def test_heuristic_score_without_bt_or_max_chars_omits_those_dimensions() -> None:
    result = score_translation("Save your changes", "Zapisz swoje zmiany", "pl")
    assert result.dimensions == {"placeholder_ok": 1.0, "glossary_ok": 1.0, "script_ok": 1.0}


def test_hard_failure_names_the_failing_dimension() -> None:
    lost = score_translation("Hello {name}", "Witaj", "pl")
    assert lost.score == 0.0
    assert lost.dimensions == {"placeholder_ok": 0.0}
    glossary = {"doNotTranslate": ["Acme"], "terms": {}}
    dnt = score_translation("Welcome to Acme", "Witamy w Firmie", "pl", glossary)
    assert dnt.score == 0.0
    assert dnt.dimensions["glossary_ok"] == 0.0


def test_soft_penalties_flip_their_dimension() -> None:
    long = score_translation("Save", "Zapisz wszystko teraz", "pl", max_chars=6)
    assert long.dimensions["length_ok"] == 0.0
    cyrillic_in_arabic = score_translation("Save your work now", "احفظ работу الآن", "ar")
    assert cyrillic_in_arabic.dimensions["script_ok"] == 0.0


# --- is_improvement -------------------------------------------------------------------------

from llm_localizator.core.quality import is_improvement  # noqa: E402

_OK = {"placeholder_ok": 1.0, "glossary_ok": 1.0, "script_ok": 1.0, "bt_overlap": 0.95}


def test_clear_score_win_and_loss_decide_on_their_own() -> None:
    assert is_improvement(0.90, _OK, 0.80, _OK)
    assert not is_improvement(0.70, _OK, 0.80, _OK)


def test_tie_goes_to_the_candidate_with_more_ok_dimensions() -> None:
    weaker = {**_OK, "bt_overlap": 0.5}
    assert is_improvement(0.79, _OK, 0.80, weaker)
    assert not is_improvement(0.80, weaker, 0.79, _OK)


def test_equal_dimensions_fall_back_to_the_higher_score() -> None:
    assert is_improvement(0.81, _OK, 0.80, _OK)
    assert not is_improvement(0.79, _OK, 0.80, _OK)
    assert not is_improvement(0.80, _OK, 0.80, _OK)


def test_fixing_a_hard_failure_wins_despite_a_lower_score() -> None:
    broken = {**_OK, "script_ok": 0.0}
    assert is_improvement(0.60, _OK, 0.70, broken)
    assert not is_improvement(0.72, broken, 0.70, _OK)


def test_missing_dimensions_mean_a_plain_score_comparison() -> None:
    assert is_improvement(0.81, None, 0.80, _OK)
    assert not is_improvement(0.80, _OK, 0.80, None)


# --- multi-sample consistency ---------------------------------------------------------------

from llm_localizator.core.quality import (  # noqa: E402
    QualityResult,
    sample_consistency,
    with_consistency,
)


def test_sample_consistency_is_the_lowest_agreement() -> None:
    assert sample_consistency("Zapisz", ["Zapisz"]) is None
    assert sample_consistency("Zapisz", ["Zapisz", "Zapisz"]) == 1.0
    close = sample_consistency("Zapisz zmiany", ["Zapisz zmiany", "Zapisz zmiany."])
    far = sample_consistency("Zapisz zmiany", ["Zapisz zmiany", "Anuluj wszystko"])
    assert close > 0.9 > 0.5 > far


def test_with_consistency_adds_dimension_and_flags_only_low_values() -> None:
    fine = with_consistency(QualityResult(0.9, []), 0.95)
    assert fine.dimensions == {"consistency": 0.95}
    assert fine.signals == []
    low = with_consistency(QualityResult(0.9, [], {"script_ok": 1.0}), 0.4)
    assert low.dimensions["consistency"] == 0.4 and low.dimensions["script_ok"] == 1.0
    assert low.signals and low.signals[0].startswith("low-consistency")
    assert with_consistency(QualityResult(0.9, []), None).dimensions is None
