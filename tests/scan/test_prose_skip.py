"""Script-aware prose and the shared source skip list."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.scan import NextIntlScanner, RawJsScanner
from llm_localizator.scan.prose import is_prose


@pytest.mark.parametrize("text", [
    "Ładowanie...",
    "Zaloguj się",
    "sign in now",
    "Войти сейчас",
    "ابحث عن النادي",
    "読み込み中",
    "กำลังโหลด",
    "नमस्ते",
])
def test_prose_catches_what_the_ascii_check_missed(text: str) -> None:
    assert is_prose(text)


def test_single_latin_word_stays_silent() -> None:
    assert not is_prose("Bridge")


def test_and_or_is_prose() -> None:
    assert is_prose("and/or")


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_docs_scripts_and_stories_are_skipped_but_help_page_is_not(tmp_path: Path) -> None:
    sentence = "<p>Sign in now</p>"
    _write(tmp_path, "app/docs/Guide.tsx", sentence)
    _write(tmp_path, "app/scripts/cli.tsx", sentence)
    _write(tmp_path, "app/Button.stories.tsx", sentence)
    _write(tmp_path, "app/HelpPage.tsx", sentence)
    result = NextIntlScanner(tmp_path, ["app"]).scan()
    files = {h.file for h in result.hardcoded}
    assert files == {"app/HelpPage.tsx"}
    assert result.files_scanned == 1


def test_unskip_brings_a_docs_path_back_but_not_node_modules(tmp_path: Path) -> None:
    sentence = "<p>Sign in now</p>"
    _write(tmp_path, "app/docs/Guide.tsx", sentence)
    _write(tmp_path, "app/node_modules/Vendor.tsx", sentence)
    result = NextIntlScanner(tmp_path, ["app"], unskip=["docs/Guide.tsx"]).scan()
    assert {h.file for h in result.hardcoded} == {"app/docs/Guide.tsx"}


def test_jsx_reports_the_new_positives(tmp_path: Path) -> None:
    src = tmp_path / "app"
    src.mkdir()
    (src / "Page.tsx").write_text(
        "<p>Ładowanie...</p><p>Zaloguj się</p><p>sign in now</p>"
        "<p>Войти сейчас</p><input placeholder=\"ابحث عن النادي\" />"
        "<span>読み込み中</span><span>กำลังโหลด</span>",
        encoding="utf-8",
    )
    found = {h.text for h in NextIntlScanner(tmp_path, ["app"]).scan().hardcoded}
    assert "Ładowanie..." in found
    assert "Zaloguj się" in found
    assert "sign in now" in found
    assert "Войти сейчас" in found
    assert "ابحث عن النادي" in found
    assert "読み込み中" in found
    assert "กำลังโหลด" in found


def test_raw_js_reports_unsegmented_prose(tmp_path: Path) -> None:
    page = tmp_path / "app"
    page.mkdir()
    (page / "index.html").write_text("<p>読み込み中</p>", encoding="utf-8")
    found = [h.text for h in RawJsScanner(tmp_path, ["app"]).scan().hardcoded]
    assert found == ["読み込み中"]


def test_slash_namespace_call_maps_to_the_stored_id(tmp_path: Path) -> None:
    src = tmp_path / "app"
    src.mkdir()
    (src / "Users.tsx").write_text(
        "const t = useTranslations('admin/users');\n"
        "const a = t('admin.users.signIn');\n"
        "const b = t('admin/users.signOut');\n",
        encoding="utf-8",
    )
    result = NextIntlScanner(tmp_path, ["app"]).scan()
    assert {(u.namespace, u.key) for u in result.usages} == {
        ("admin/users", "signIn"),
        ("admin/users", "signOut"),
    }


def test_bracket_i18n_call_is_a_usage(tmp_path: Path) -> None:
    src = tmp_path / "app"
    src.mkdir()
    (src / "ui.js").write_text("const label = i18n['t']('nav.home');\n", encoding="utf-8")
    result = RawJsScanner(tmp_path, ["app"]).scan()
    assert any(u.namespace == "nav" and u.key == "home" for u in result.usages)


@pytest.mark.parametrize("text", ["{count} items", "Items: {count}", "Hello {name}!", "{n} zawodników"])
def test_prose_with_braces_is_prose(text: str) -> None:
    assert is_prose(text)


@pytest.mark.parametrize("text", ["{count}", "{ user.name }", "{{ title }}", "{a} {{b}}"])
def test_single_brace_expression_is_not_prose(text: str) -> None:
    assert not is_prose(text)


def test_scripts_new_single_words_are_prose() -> None:
    for word in ["შესვლა", "Մուտք", "প্রবেশ", "உள்நுழை", "ចូល"]:
        assert is_prose(word)
