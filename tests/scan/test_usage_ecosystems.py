"""Key usage in non-JavaScript ecosystems (ADR-141)."""

from __future__ import annotations

import pytest

from llm_localizator.scan.usage_calls import KeyUsage, collect_ecosystem_usage

CASES = [
    ("A.kt", ".kt", "Text(stringResource(R.string.app_name))\ngetString(R.plurals.files)\n", {"app_name", "files"}),
    ("main.xml", ".xml", '<Button android:text="@string/save"/>\n', {"save"}),
    ("V.swift", ".swift", 'NSLocalizedString("save_button", comment: "")\nString(localized: "other")\n', {"save_button", "other"}),
    ("a.dart", ".dart", "Text(AppLocalizations.of(context)!.welcomeTitle); context.l10n.bye\n", {"welcomeTitle", "bye"}),
    ("a.cs", ".cs", 'var a = Resources.SaveLabel; var b = _localizer["Hello"];\n', {"SaveLabel", "Hello"}),
    ("M.java", ".java", 'bundle.getString("menu.open"); msg(R.string.title)\n', {"menu.open", "title"}),
    ("a.rb", ".rb", "I18n.t('users.show.title')\n", {"users.show.title"}),
    ("m.rs", ".rs", 'let s = t!("greeting");\n', {"greeting"}),
]


@pytest.mark.parametrize("name,suffix,text,expected", CASES)
def test_keys_found(name: str, suffix: str, text: str, expected: set[str]) -> None:
    usage = KeyUsage()
    collect_ecosystem_usage(text, name, suffix, usage)
    assert usage.eco == expected


def test_comments_and_other_suffixes_are_ignored() -> None:
    usage = KeyUsage()
    collect_ecosystem_usage("/* R.string.example */\nx = 1\n", "A.kt", ".kt", usage)
    collect_ecosystem_usage("R.string.other", "a.txt", ".txt", usage)
    assert not usage.eco
