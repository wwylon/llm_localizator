"""Script-family validators and latin token allowlists."""

from __future__ import annotations

from llm_localizator.core.latin_tokens import (
    extract_identifier_spans,
    extract_prose_latin_runs,
    source_latin_allowlist,
)
from llm_localizator.core.script_checks import (
    check_foreign_script,
    check_script_issues,
    foreign_script_hard_gate,
)


def test_tournaments_half_english() -> None:
    issues = check_script_issues("Tournaments", "التournaments", "ar")
    assert any("latin not in source" in i and "ournaments" in i for i in issues)


def test_nav_staff_cjk() -> None:
    issues = check_script_issues("Staff", "次级人员", "ar")
    assert any("cjk" in i for i in issues)
    assert foreign_script_hard_gate("次级人员", "ar") is not None


def test_show_archived_cyrillic() -> None:
    issues = check_script_issues("Show archived", "покажи المحفوظات", "ar")
    assert any("cyrillic" in i for i in issues)


def test_access_latin_from_source_ok() -> None:
    issues = check_script_issues(
        "Access Denied",
        "Access مكشوف للاستخدام الإداري",
        "ar",
    )
    assert not any("latin not in source" in i for i in issues)
    assert not any("unexpected script" in i for i in issues)


def test_latin_only_ui() -> None:
    issues = check_script_issues("Tournaments", "Tournaments", "ar")
    assert any("latin-only" in i for i in issues)


def test_pure_arabic_clean() -> None:
    assert check_script_issues("Save", "حفظ", "ar") == []


def test_identifier_atomic_allowlist() -> None:
    src = "Env: BRIDGE_SUPER_ADMIN_EMAILS"
    ids, prose = source_latin_allowlist(src)
    assert "BRIDGE_SUPER_ADMIN_EMAILS" in ids
    assert "super" not in prose
    assert "admin" not in prose

    clean = check_script_issues(
        src, "استخدم BRIDGE_SUPER_ADMIN_EMAILS", "ar",
    )
    assert not any("latin" in i for i in clean)

    truncated = check_script_issues(
        src, "استخدم BRIDGE_SUPER_ADMIN", "ar",
    )
    assert any("identifier not in source" in i for i in truncated)

    fragment = check_script_issues(src, "استخدم super هنا", "ar")
    assert any("latin not in source" in i and "super" in i for i in fragment)


def test_cyrillic_locale_latin_only() -> None:
    issues = check_script_issues("Tournaments", "Tournaments", "ru")
    assert any("latin-only" in i for i in issues)
    assert check_script_issues("Tournaments", "Турниры", "ru") == []


def test_polish_cjk_foreign_only() -> None:
    issues = check_script_issues("nie", "nie翻譯", "pl")
    assert any("cjk" in i for i in issues)
    assert not any("latin not in source" in i for i in issues)


def test_icu_placeholder_stripped() -> None:
    issues = check_script_issues(
        "{n} users",
        "{n} مستخدمون",
        "ar",
    )
    assert issues == []


def test_hangul_is_cjk() -> None:
    assert check_foreign_script("직원", "ko") is None
    assert check_foreign_script("직원ключ", "ko") is not None


def test_extract_helpers() -> None:
    assert extract_identifier_spans("see FOO_BAR now") == ["FOO_BAR"]
    assert "ournaments" in extract_prose_latin_runs("التournaments")


def test_more_scripts_are_recognised() -> None:
    from llm_localizator.core.scripts import char_script

    for ch, name in [("ა", "georgian"), ("Ա", "armenian"), ("ব", "bengali"),
                     ("த", "tamil"), ("ក", "khmer"), ("ਪ", "gurmukhi")]:
        assert char_script(ch) == name
    # Existing scripts are unchanged.
    assert char_script("a") == "latin" and char_script("ж") == "cyrillic"
    assert char_script("न") == "devanagari" and char_script("ก") == "thai"
