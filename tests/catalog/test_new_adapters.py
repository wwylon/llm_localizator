"""Round-trip tests for the six new catalog adapters."""

from __future__ import annotations

import json
from pathlib import Path


from llm_localizator.catalog import build_catalog


# ---------------------------------------------------------------------------
# multilang-json
# ---------------------------------------------------------------------------

def test_multilang_json_load(tmp_path: Path) -> None:
    data = {
        "terms": {
            "trick": {"pl": "lewa", "ar": "خدعة"},
            "declarer": {"pl": "rozgrywający"},
        },
        "doNotTranslate": ["Stayman"],
    }
    (tmp_path / "glossary.json").write_text(json.dumps(data), encoding="utf-8")
    cat = build_catalog("multilang-json", tmp_path, "glossary.json")
    pl = cat.load("pl")
    assert pl["trick"] == "lewa"
    assert pl["declarer"] == "rozgrywający"
    assert "doNotTranslate" not in pl

    ar = cat.load("ar")
    assert ar["trick"] == "خدعة"
    assert "declarer" not in ar


def test_multilang_json_save_merges(tmp_path: Path) -> None:
    data = {"terms": {"trick": {"pl": "lewa"}}}
    (tmp_path / "glossary.json").write_text(json.dumps(data), encoding="utf-8")
    cat = build_catalog("multilang-json", tmp_path, "glossary.json")
    cat.save("de", None, {"trick": "Stich", "declarer": "Ansager"})
    raw = json.loads((tmp_path / "glossary.json").read_text())
    assert raw["terms"]["trick"]["pl"] == "lewa"
    assert raw["terms"]["trick"]["de"] == "Stich"
    assert raw["terms"]["declarer"]["de"] == "Ansager"


def test_multilang_json_roundtrip(tmp_path: Path) -> None:
    cat = build_catalog("multilang-json", tmp_path, "messages/{namespace}.json")
    cat.save("en", "terms", {"apple": "apple", "house": "house"})
    cat.save("pl", "terms", {"apple": "jabłko", "house": "dom"})
    assert cat.load("en", "terms") == {"apple": "apple", "house": "house"}
    assert cat.load("pl", "terms") == {"apple": "jabłko", "house": "dom"}


def test_multilang_json_locales_present_reads_sectioned_file(tmp_path: Path) -> None:
    data = {
        "terms": {
            "trick": {"pl": "lewa", "de": "Stich"},
            "declarer": {"ar": "المعلن"},
        },
        "doNotTranslate": ["Stayman"],
    }
    (tmp_path / "glossary.json").write_text(json.dumps(data), encoding="utf-8")
    cat = build_catalog("multilang-json", tmp_path, "glossary.json", source_locale="en")
    assert cat.locales_present() == ["ar", "de", "pl"]


# ---------------------------------------------------------------------------
# csv
# ---------------------------------------------------------------------------

def test_csv_load(tmp_path: Path) -> None:
    csv_text = "key,en,pl,de\nlogin,Sign in,Zaloguj,Anmelden\nlogout,Sign out,,Abmelden\n"
    (tmp_path / "auth.csv").write_text(csv_text, encoding="utf-8")
    cat = build_catalog("csv", tmp_path, "{namespace}.csv")
    en = cat.load("en", "auth")
    assert en["login"] == "Sign in"
    assert en["logout"] == "Sign out"
    pl = cat.load("pl", "auth")
    assert pl["login"] == "Zaloguj"
    assert "logout" not in pl  # empty → not present


def test_csv_save_adds_column(tmp_path: Path) -> None:
    csv_text = "key,en\nlogin,Sign in\n"
    (tmp_path / "auth.csv").write_text(csv_text, encoding="utf-8")
    cat = build_catalog("csv", tmp_path, "{namespace}.csv")
    cat.save("pl", "auth", {"login": "Zaloguj"})
    text = (tmp_path / "auth.csv").read_text()
    assert "pl" in text
    assert "Zaloguj" in text
    assert "Sign in" in text  # en preserved


# ---------------------------------------------------------------------------
# php-array
# ---------------------------------------------------------------------------

def test_php_array_load(tmp_path: Path) -> None:
    php = "<?php\nreturn [\n    'login' => 'Sign in',\n    'logout' => 'Sign out',\n];\n"
    path = tmp_path / "en" / "auth.php"
    path.parent.mkdir()
    path.write_text(php, encoding="utf-8")
    cat = build_catalog("php-array", tmp_path, "{locale}/{namespace}.php")
    msgs = cat.load("en", "auth")
    assert msgs["login"] == "Sign in"
    assert msgs["logout"] == "Sign out"


def test_php_array_save(tmp_path: Path) -> None:
    cat = build_catalog("php-array", tmp_path, "{locale}/{namespace}.php")
    cat.save("pl", "auth", {"login": "Zaloguj", "logout": "Wyloguj"})
    text = (tmp_path / "pl" / "auth.php").read_text()
    assert "'login' => 'Zaloguj'" in text
    assert "<?php" in text


def test_php_array_escaped_quotes(tmp_path: Path) -> None:
    cat = build_catalog("php-array", tmp_path, "{locale}/{namespace}.php")
    cat.save("en", "test", {"key": "It's a 'test'"})
    msgs = cat.load("en", "test")
    assert msgs["key"] == "It's a 'test'"


# ---------------------------------------------------------------------------
# go-i18n
# ---------------------------------------------------------------------------

def test_go_i18n_load(tmp_path: Path) -> None:
    data = [
        {"id": "Greet", "translation": "Hello {{.Name}}!"},
        {"id": "Count", "translation": {"one": "One item", "other": "{{.Count}} items"}},
    ]
    path = tmp_path / "en.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cat = build_catalog("go-i18n", tmp_path, "{locale}.json")
    msgs = cat.load("en")
    assert msgs["Greet"] == "Hello {{.Name}}!"
    assert "one" in msgs["Count"]  # plural stored as JSON string


def test_go_i18n_roundtrip(tmp_path: Path) -> None:
    cat = build_catalog("go-i18n", tmp_path, "{locale}.json")
    cat.save("pl", None, {"Greet": "Cześć {{.Name}}!"})
    msgs = cat.load("pl")
    assert msgs["Greet"] == "Cześć {{.Name}}!"


# ---------------------------------------------------------------------------
# ios-strings
# ---------------------------------------------------------------------------

def test_ios_strings_load(tmp_path: Path) -> None:
    strings = '/* greeting */\n"GREET" = "Hello!";\n"LOGOUT" = "Sign out";\n'
    path = tmp_path / "en.lproj" / "Localizable.strings"
    path.parent.mkdir()
    path.write_text(strings, encoding="utf-8")
    cat = build_catalog("ios-strings", tmp_path, "{locale}.lproj/Localizable.strings")
    msgs = cat.load("en")
    assert msgs["GREET"] == "Hello!"
    assert msgs["LOGOUT"] == "Sign out"


def test_ios_strings_escape_roundtrip(tmp_path: Path) -> None:
    cat = build_catalog("ios-strings", tmp_path, "{locale}.lproj/Localizable.strings")
    cat.save("en", None, {"KEY": 'Say "hello"\nand goodbye'})
    msgs = cat.load("en")
    assert msgs["KEY"] == 'Say "hello"\nand goodbye'


# ---------------------------------------------------------------------------
# properties
# ---------------------------------------------------------------------------

def test_properties_load(tmp_path: Path) -> None:
    props = "# auth\nloginTitle=Sign in\nregisterTitle=Create account\n"
    path = tmp_path / "messages_en.properties"
    path.write_text(props, encoding="utf-8")
    cat = build_catalog("properties", tmp_path, "messages_{locale}.properties")
    msgs = cat.load("en")
    assert msgs["loginTitle"] == "Sign in"
    assert msgs["registerTitle"] == "Create account"


def test_properties_save(tmp_path: Path) -> None:
    cat = build_catalog("properties", tmp_path, "messages_{locale}.properties")
    cat.save("pl", None, {"loginTitle": "Zaloguj się"})
    text = (tmp_path / "messages_pl.properties").read_text()
    assert "loginTitle=Zaloguj" in text


def test_properties_unicode_escape_roundtrip(tmp_path: Path) -> None:
    cat = build_catalog("properties", tmp_path, "messages_{locale}.properties")
    cat.save("ar", None, {"greet": "مرحبا"})
    msgs = cat.load("ar")
    assert msgs["greet"] == "مرحبا"
