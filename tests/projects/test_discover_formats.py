"""Tests for the new format-detection probes in discover_collections."""

from __future__ import annotations

import csv
import json
from pathlib import Path


from llm_localizator.projects.collections import discover_collections


def _formats(proposals: list[dict]) -> set[str]:
    return {p["format"] for p in proposals}


# ---------------------------------------------------------------------------
# multilang-json
# ---------------------------------------------------------------------------

def test_discover_multilang_json(tmp_path: Path) -> None:
    data = {
        "terms": {
            "trick": {"pl": "lewa", "en": "trick", "de": "Stich"},
        }
    }
    (tmp_path / "glossary.json").write_text(json.dumps(data), encoding="utf-8")
    proposals = discover_collections(tmp_path)
    assert any(p["format"] == "multilang-json" for p in proposals)
    ml = next(p for p in proposals if p["format"] == "multilang-json")
    assert set(ml["locales"]) >= {"pl", "en", "de"}


def test_discover_multilang_json_skips_plain_json(tmp_path: Path) -> None:
    # A plain per-locale JSON file should NOT be detected as multilang-json
    data = {"loginTitle": "Sign in", "registerTitle": "Create account"}
    (tmp_path / "en.json").write_text(json.dumps(data), encoding="utf-8")
    proposals = discover_collections(tmp_path)
    assert not any(p["format"] == "multilang-json" for p in proposals)


# ---------------------------------------------------------------------------
# csv
# ---------------------------------------------------------------------------

def test_discover_csv(tmp_path: Path) -> None:
    rows = [["key", "en", "pl", "de"],
            ["login", "Sign in", "Zaloguj", "Anmelden"]]
    with (tmp_path / "auth.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    proposals = discover_collections(tmp_path)
    assert any(p["format"] == "csv" for p in proposals)
    csv_p = next(p for p in proposals if p["format"] == "csv")
    assert set(csv_p["locales"]) >= {"en", "pl", "de"}


def test_discover_csv_skips_no_locale_columns(tmp_path: Path) -> None:
    rows = [["id", "label", "value"], ["1", "foo", "bar"]]
    with (tmp_path / "data.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    proposals = discover_collections(tmp_path)
    assert not any(p["format"] == "csv" for p in proposals)


# ---------------------------------------------------------------------------
# php-array
# ---------------------------------------------------------------------------

def test_discover_php_array(tmp_path: Path) -> None:
    for locale in ("en", "pl"):
        d = tmp_path / locale
        d.mkdir()
        (d / "auth.php").write_text(
            "<?php\nreturn ['key' => 'value'];\n", encoding="utf-8"
        )
    proposals = discover_collections(tmp_path)
    assert any(p["format"] == "php-array" for p in proposals)


# ---------------------------------------------------------------------------
# go-i18n
# ---------------------------------------------------------------------------

def test_discover_go_i18n(tmp_path: Path) -> None:
    for locale in ("en", "pl"):
        (tmp_path / f"{locale}.json").write_text(
            json.dumps([{"id": "Greet", "translation": "Hello"}]), encoding="utf-8"
        )
    proposals = discover_collections(tmp_path)
    assert any(p["format"] == "go-i18n" for p in proposals)


# ---------------------------------------------------------------------------
# ios-strings
# ---------------------------------------------------------------------------

def test_discover_ios_strings(tmp_path: Path) -> None:
    for locale in ("en", "pl"):
        d = tmp_path / f"{locale}.lproj"
        d.mkdir()
        (d / "Localizable.strings").write_text('"KEY" = "val";\n', encoding="utf-8")
    proposals = discover_collections(tmp_path)
    assert any(p["format"] == "ios-strings" for p in proposals)


# ---------------------------------------------------------------------------
# properties
# ---------------------------------------------------------------------------

def test_discover_properties(tmp_path: Path) -> None:
    for locale in ("en", "pl"):
        (tmp_path / f"messages_{locale}.properties").write_text(
            "key=value\n", encoding="utf-8"
        )
    proposals = discover_collections(tmp_path)
    assert any(p["format"] == "properties" for p in proposals)
