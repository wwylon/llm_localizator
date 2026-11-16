"""Translation validation rules.

Ported from bridge's TestValidateTranslation, plus new coverage for the
word-boundary fix: glossary rules previously never fired for Arabic, Hebrew, or
CJK because Python's ``\\b`` is defined against ``\\w``.
"""

from __future__ import annotations

import pytest

from llm_localizator.core.validate import (
    check_agent_artifacts,
    check_expansion_band,
    check_max_chars,
    check_translation_length,
    check_translator_meta,
    classify_failure,
    glossary_violations,
    term_pattern,
    validate_translation,
    validate_translation_detailed,
)


def messages(issues) -> list[str]:
    return [i.message for i in issues]


@pytest.fixture
def glossary() -> dict:
    return {
        "doNotTranslate": ["Stayman", "Blackwood"],
        "terms": {
            "trick": {"pl": "lewa", "pl_forbidden": ["sztuczka", "trik"]},
            "bridge": {"pl": "brydż", "ar": "بريدج"},
        },
    }


# ---- placeholders ----------------------------------------------------------

def test_accepts_correct_translation(glossary: dict) -> None:
    ok, reason = validate_translation("Hello {name}", "Witaj {name}", "pl", glossary)
    assert ok, reason


def test_rejects_missing_placeholder(glossary: dict) -> None:
    ok, reason = validate_translation("Hello {name}", "Witaj", "pl", glossary)
    assert not ok
    assert "missing placeholders" in reason


def test_rejects_extra_placeholder(glossary: dict) -> None:
    ok, reason = validate_translation("Hello", "Witaj {name}", "pl", glossary)
    assert not ok
    assert "extra placeholders" in reason


# ---- plurals ---------------------------------------------------------------

def test_rejects_plural_collapsed_to_plain(glossary: dict) -> None:
    en = "{n, plural, one {# trick} other {# tricks}}"
    ok, reason = validate_translation(en, "{n} lew", "pl", glossary)
    assert not ok
    assert "not" in reason


def test_rejects_missing_plural_category_for_polish(glossary: dict) -> None:
    en = "{n, plural, one {# trick} other {# tricks}}"
    pl = "{n, plural, one {# lewa} other {# lew}}"  # missing few/many
    ok, reason = validate_translation(en, pl, "pl", glossary)
    assert not ok
    assert "few" in reason and "many" in reason


def test_accepts_full_polish_plural_categories(glossary: dict) -> None:
    en = "{n, plural, one {# trick} other {# tricks}}"
    pl = "{n, plural, one {# lewa} few {# lewy} many {# lew} other {# lewy}}"
    ok, reason = validate_translation(en, pl, "pl", glossary)
    assert ok, reason


def test_accepts_all_six_arabic_categories() -> None:
    en = "{n, plural, one {# point} other {# points}}"
    ar = (
        "{n, plural, zero {# نقطة} one {نقطة واحدة} two {نقطتان} "
        "few {# نقاط} many {# نقطة} other {# نقطة}}"
    )
    ok, reason = validate_translation(en, ar, "ar", {})
    assert ok, reason


# ---- shape -----------------------------------------------------------------

def test_rejects_overlong_output(glossary: dict) -> None:
    ok, reason = validate_translation("Bid", "x" * 500, "pl", glossary)
    assert not ok
    assert "too long" in reason


def test_rejects_unexpected_newlines(glossary: dict) -> None:
    ok, reason = validate_translation("Claim", "Zagraj\nresztę", "pl", glossary)
    assert not ok
    assert "newlines" in reason


def test_allows_newlines_when_source_has_them(glossary: dict) -> None:
    ok, reason = validate_translation("a\nb", "x\ny", "pl", glossary)
    assert ok, reason


# ---- glossary --------------------------------------------------------------

def test_rejects_do_not_translate_term_dropped(glossary: dict) -> None:
    ok, reason = validate_translation("Use Stayman here", "Użyj tutaj", "pl", glossary)
    assert not ok
    assert "Stayman" in reason


def test_accepts_do_not_translate_term_kept(glossary: dict) -> None:
    ok, reason = validate_translation("Use Stayman", "Użyj Stayman", "pl", glossary)
    assert ok, reason


def test_rejects_forbidden_glossary_variant(glossary: dict) -> None:
    ok, reason = validate_translation("One trick", "Jedna sztuczka", "pl", glossary)
    assert not ok
    assert "sztuczka" in reason


def test_missing_approved_term_is_advisory_not_blocking(glossary: dict) -> None:
    """The approved-term rule is exact-substring, so inflected forms are false
    positives. It reports, it does not reject (ADR-8)."""
    issues = glossary_violations("One trick", "Jedna karta", glossary, "pl")
    assert [i.kind for i in issues] == ["missing-approved"]
    assert not issues[0].blocking

    ok, _ = validate_translation("One trick", "Jedna karta", "pl", glossary)
    assert ok, "an advisory glossary issue must not reject the translation"


def test_forbidden_variant_is_blocking(glossary: dict) -> None:
    issues = glossary_violations("One trick", "Jedna sztuczka", glossary, "pl")
    assert any(i.kind == "forbidden-variant" and i.blocking for i in issues)


def test_missing_dnt_is_blocking(glossary: dict) -> None:
    issues = glossary_violations("Use Stayman here", "Użyj tutaj", glossary, "pl")
    assert any(i.kind == "missing-dnt" and i.blocking for i in issues)


def test_approved_term_matches_english_inflection(glossary: dict) -> None:
    # "tricks" must still trigger the "trick" glossary rule.
    assert any("lewa" in m for m in messages(
        glossary_violations("Two tricks", "Dwie karty", glossary, "pl")
    ))


def test_derivational_source_form_does_not_trigger_base_glossary_term() -> None:
    """Regression from bridge F-012: 'bidding' must not fire the 'bid' rule.

    Polish correctly renders the auction process as ``licytacja``; demanding
    ``zapowiedź`` (a single call) was 19 false V13 advisories.
    """
    gloss = {"terms": {"bid": {"pl": "zapowiedź"}}}
    issues = glossary_violations("Bidding is open", "Licytacja trwa", gloss, "pl")
    assert issues == []


def test_plural_source_form_still_triggers_glossary_term() -> None:
    gloss = {"terms": {"bid": {"pl": "zapowiedź"}}}
    issues = glossary_violations("Two bids", "Dwie karty", gloss, "pl")
    assert any(i.kind == "missing-approved" for i in issues)


# ---- homonym gating --------------------------------------------------------

def test_forbidden_variant_ignores_homonyms_when_source_lacks_the_term() -> None:
    """Regression from bridge's live catalogue.

    The glossary forbids Arabic 'عرض' as a rendering of "bid", but the same
    word ordinarily means "view". Scanning the translation unconditionally
    reported "Public view only" as a bid mistranslation.
    """
    gloss = {"terms": {"bid": {"ar_forbidden": ["عرض"]}}}
    en = "Public view only - no hidden hands (Kibitzer mode)."
    ar = "عرض عام فقط - بدون أيد مخفية (وضع المراقب)."
    assert glossary_violations(en, ar, gloss, "ar") == []


def test_forbidden_variant_still_fires_when_source_uses_the_term() -> None:
    gloss = {"terms": {"bid": {"ar_forbidden": ["عرض"]}}}
    issues = glossary_violations("Make a bid now", "عرض الآن", gloss, "ar")
    assert [i.kind for i in issues] == ["forbidden-variant"]
    assert issues[0].blocking


def test_approved_term_not_demanded_when_source_lacks_the_term(glossary: dict) -> None:
    assert glossary_violations("Hello there", "Witaj", glossary, "pl") == []


# ---- explicit ICU value selectors -----------------------------------------

def test_explicit_zero_selector_satisfies_zero_category() -> None:
    """Regression from bridge's live catalogue: ``=0`` is stronger than ``zero``.

    ``ar/clubs.calendarGoingCount`` uses ``=0`` plus all five Arabic categories
    and was reported as missing ``zero``.
    """
    en = "{n, plural, =0 {No one going yet} one {# going} other {# going}}"
    ar = (
        "{n, plural, =0 {لم يسجل أحد بعد} one {شخص واحد} two {شخصان} "
        "few {# أشخاص} many {# شخصا} other {# شخص}}"
    )
    ok, reason = validate_translation(en, ar, "ar", {})
    assert ok, reason


def test_named_zero_category_still_accepted() -> None:
    en = "{n, plural, one {# point} other {# points}}"
    ar = (
        "{n, plural, zero {# نقطة} one {نقطة} two {نقطتان} "
        "few {# نقاط} many {# نقطة} other {# نقطة}}"
    )
    ok, reason = validate_translation(en, ar, "ar", {})
    assert ok, reason


def test_missing_zero_is_still_rejected_for_arabic() -> None:
    en = "{n, plural, one {# point} other {# points}}"
    ar = "{n, plural, one {# نقطة} two {نقطتان} few {# نقاط} many {# نقطة} other {# نقطة}}"
    ok, reason = validate_translation(en, ar, "ar", {})
    assert not ok
    assert "zero" in reason


# ---- the word-boundary fix -------------------------------------------------

def test_arabic_do_not_translate_term_is_actually_enforced() -> None:
    """Regression: with ``\\b`` boundaries this returned no problems at all.

    ``\\b`` is defined against ``\\w``; between an Arabic letter and a Latin
    letter the boundary positions do not work out, so the rule silently passed
    every Arabic translation regardless of content.
    """
    gloss = {"doNotTranslate": ["Stayman"], "terms": {}}
    problems = glossary_violations("Use Stayman here", "استخدم هنا", gloss, "ar")
    assert problems, "do-not-translate violation must be detected for Arabic output"
    assert "Stayman" in problems[0].message
    assert problems[0].blocking


def test_arabic_do_not_translate_term_kept_is_clean() -> None:
    gloss = {"doNotTranslate": ["Stayman"], "terms": {}}
    assert glossary_violations("Use Stayman here", "استخدم Stayman هنا", gloss, "ar") == []


def test_arabic_approved_term_enforced() -> None:
    gloss = {"terms": {"bridge": {"ar": "بريدج"}}}
    assert glossary_violations("Play bridge", "العب الورق", gloss, "ar")
    assert glossary_violations("Play bridge", "العب بريدج", gloss, "ar") == []


def test_unsegmented_script_uses_substring_containment() -> None:
    """Chinese has no word boundaries, so containment is the only sane test."""
    gloss = {"doNotTranslate": ["Stayman"], "terms": {}}
    assert glossary_violations("Use Stayman", "使用Stayman约定", gloss, "zh") == []
    assert glossary_violations("Use Stayman", "使用这个约定", gloss, "zh")


def test_term_pattern_does_not_match_substring() -> None:
    import re

    assert re.search(term_pattern("bid"), "bid now")
    assert not re.search(term_pattern("bid"), "forbidden")


def test_term_pattern_with_suffix_matches_inflection() -> None:
    import re

    assert re.search(term_pattern("bid", allow_suffix=True), "bidding now")
    assert not re.search(term_pattern("bid", allow_suffix=True), "forbidden")


# ---- length ----------------------------------------------------------------

def test_length_ok_within_band() -> None:
    # 14 chars EN -> 17 chars PL is a ratio of 1.21, inside Polish's 1.10-1.50.
    assert check_translation_length("Start the game", "Rozpocznij partię", "pl") is None


def test_length_warns_over_max_chars() -> None:
    warn = check_translation_length("Bid", "Licytowanie", "pl", max_chars=5)
    assert warn is not None
    assert "maxChars" in warn


def test_length_skips_band_for_short_strings() -> None:
    assert check_translation_length("Bid", "Licytowanie bardzo", "pl") is None


def test_length_warns_suspiciously_long() -> None:
    warn = check_translation_length("Start the game", "x" * 60, "pl")
    assert warn is not None
    assert "long" in warn


def test_length_warns_suspiciously_short() -> None:
    warn = check_translation_length("Start the game now please", "ab", "de")
    assert warn is not None
    assert "short" in warn


def test_length_no_band_for_unknown_locale() -> None:
    assert check_translation_length("Start the game", "whatever text", "xx") is None


# ---- the two halves, used separately by validate ---------------------------

def test_max_chars_is_independent_of_the_band() -> None:
    assert check_max_chars("Licytowanie", 5) is not None
    assert check_max_chars("Licytowanie", 50) is None
    assert check_max_chars("Licytowanie", None) is None


def test_expansion_band_is_independent_of_max_chars() -> None:
    assert check_expansion_band("Start the game", "x" * 60, "pl") is not None
    assert check_expansion_band("Start the game", "Rozpocznij partię", "pl") is None


def test_expansion_band_uses_base_language() -> None:
    """Region tags like pt-BR must hit the same band as pt."""
    long_pt = check_expansion_band("Start the game", "x" * 60, "pt")
    long_br = check_expansion_band("Start the game", "x" * 60, "pt-BR")
    assert long_pt is not None
    assert long_br == long_pt


def test_budget_takes_precedence_over_band() -> None:
    """When both fire, the actionable one is reported."""
    warn = check_translation_length("Start the game", "x" * 60, "pl", max_chars=5)
    assert warn is not None and "maxChars" in warn


def test_casefold_matches_german_eszett() -> None:
    import re

    from llm_localizator.core.validate import _contains

    assert _contains("STRASSE", "straße", locale="de", flags=re.IGNORECASE)


# ---- V32 literal presence -----------------------------------------------

from llm_localizator.core.validate import check_literal_presence


def test_v32_url_dropped_is_rejected() -> None:
    ok, msg = validate_translation(
        "Visit https://example.com for details", "Voir example.com pour les détails", "fr", {}
    )
    assert not ok
    assert "literal" in msg.lower()


def test_v32_email_present_passes() -> None:
    ok, _ = validate_translation("Email support@co.com now", "support@co.com kontaktieren", "de", {})
    assert ok


def test_v32_no_literals_passes() -> None:
    ok, _ = validate_translation("Save changes", "Zapisz zmiany", "pl", {})
    assert ok


def test_v32_code_dispatched_correctly() -> None:
    _, failures = validate_translation_detailed(
        "See https://example.com", "Voir example", "fr", {}
    )
    assert any(f.id == "V32" for f in failures)


def test_v32_localised_acronym_is_not_rejected() -> None:
    ok, _ = validate_translation("Press OK to continue", "اضغط موافق للمتابعة", "ar", {})
    assert ok


def test_check_literal_presence_snake_case() -> None:
    msg = check_literal_presence("Use auth_token for login", "Verwenden Sie für die Anmeldung")
    assert msg is not None and "auth_token" in msg


# ---- V33 untranslated fragments -----------------------------------------



def test_v33_fires_on_english_stopwords_in_french() -> None:
    _, w = validate_translation_detailed(
        "Save the document", "Enregistrez the document and save", "fr", {}
    )
    assert any(f.id == "V33" for f in w)


def test_v33_silent_for_english_target() -> None:
    _, w = validate_translation_detailed("Save changes", "Save changes", "en", {})
    assert not any(f.id == "V33" for f in w)


def test_v33_silent_for_single_stopword() -> None:
    _, w = validate_translation_detailed(
        "Save the document", "Enregistrez the fichier", "fr", {}
    )
    assert not any(f.id == "V33" for f in w)


# ---- V34 typography -----------------------------------------------------



def test_v34_french_missing_space_before_colon() -> None:
    _, w = validate_translation_detailed("Error:", "Erreur:", "fr", {})
    assert any(f.id == "V34" for f in w)


def test_v34_french_space_before_colon_passes() -> None:
    _, w = validate_translation_detailed("Error:", "Erreur :", "fr", {})
    assert not any(f.id == "V34" for f in w)


def test_v34_noop_for_unregistered_locale() -> None:
    _, w = validate_translation_detailed("Save", "Guardar", "es", {})
    assert not any(f.id == "V34" for f in w)


# ---- V13 morphology -----------------------------------------------------

def test_v13_inflected_polish_form_passes() -> None:
    glossary = {"terms": {"bid": {"pl": "zapowiedź"}}}
    issues = glossary_violations("Place a bid", "Złóż zapowiedzią", glossary, "pl")
    assert not any(i.kind == "missing-approved" for i in issues)


def test_v13_wrong_polish_term_still_fires() -> None:
    glossary = {"terms": {"bid": {"pl": "zapowiedź"}}}
    issues = glossary_violations("Place a bid", "Złóż aukcją", glossary, "pl")
    assert any(i.kind == "missing-approved" for i in issues)


# ---- V14 display-width --------------------------------------------------

def test_v14_cjk_double_width_counts_correctly() -> None:
    # "確認" = 2 CJK chars = display-width 4; EN "OK" = width 2; ratio = 2.0
    # Should be within band (or no band), not "suspiciously long"
    ok = check_expansion_band("OK", "確認", "ja")
    assert ok is None or "suspiciously" not in ok


# ---- context sha in state -----------------------------------------------

from llm_localizator.catalog.state import make_entry, needs_translation as _needs_translation


def test_context_sha_change_marks_stale() -> None:
    entry = make_entry("Save", "m", note="button label")
    assert not _needs_translation("Save", entry, note="button label")
    assert _needs_translation("Save", entry, note="error message")


def test_missing_context_sha_is_not_stale() -> None:
    entry = make_entry("Save", "m")  # no note → no context_sha
    assert not _needs_translation("Save", entry, note="error message")


def test_v98_flags_target_keys_missing_from_the_source(tmp_path, make_config, make_catalog) -> None:
    from llm_localizator.pipeline.validate import run_validation
    from tests.conftest import setup_project

    setup_project(tmp_path, {"a": "A", "b": "B", "c": "C", "d": "D"},
                  existing={"a": "A", "b": "B", "c": "C", "d": "D", "flat_key": "x", "other_flat": "y"})
    cfg = make_config(tmp_path)
    codes = [f.check for f in run_validation(cfg, make_catalog(cfg), locales=["pl"]).findings]
    assert "V98" in codes and "V99" not in codes


def test_v98_ignores_plural_variants_and_partial_targets(tmp_path, make_config, make_catalog) -> None:
    from llm_localizator.pipeline.validate import run_validation
    from tests.conftest import setup_project

    setup_project(tmp_path, {"n_one": "1", "n_other": "many", "a": "A", "b": "B", "c": "C", "d": "D"},
                  existing={"n_one": "1", "n_few": "f", "n_many": "m", "n_other": "o", "a": "A", "b": "B", "c": "C"})
    cfg = make_config(tmp_path)
    codes = [f.check for f in run_validation(cfg, make_catalog(cfg), locales=["pl"]).findings]
    assert "V98" not in codes


def test_v99_flags_a_mostly_empty_target(tmp_path, make_config, make_catalog) -> None:
    from llm_localizator.pipeline.validate import run_validation
    from tests.conftest import setup_project

    setup_project(tmp_path, {"a": "A", "b": "B", "c": "C", "d": "D"}, existing={"a": "A"})
    cfg = make_config(tmp_path)
    codes = [f.check for f in run_validation(cfg, make_catalog(cfg), locales=["pl"]).findings]
    assert "V99" in codes and "V98" not in codes

def test_rejects_key_trailer(glossary: dict) -> None:
    ok, reason = validate_translation(
        "Pre-run analysis", "Analiza [key: nav_analysis]", "pl", glossary,
    )
    assert not ok
    assert "[key:" in reason
    assert classify_failure(reason) == "V43"


def test_rejects_wrapped_quotes(glossary: dict) -> None:
    ok, reason = validate_translation("Hello", '"Czesc"', "pl", glossary)
    assert not ok
    assert "quotes" in reason


def test_accepts_clean_after_scrub(glossary: dict) -> None:
    ok, reason = validate_translation(
        "Pre-run analysis", "Analiza przed uruchomieniem", "pl", glossary,
    )
    assert ok, reason


def test_translator_meta_warning_on_short_label() -> None:
    msg = check_translator_meta(
        "Pre-run analysis",
        "Analiza przed uruchomieniem (zamiast 'x', co nie jest naturalne)",
    )
    assert msg is not None


def test_agent_artifacts_helper() -> None:
    assert check_agent_artifacts("a", "b [key: a]") is not None
    assert check_agent_artifacts("a", "b") is None
