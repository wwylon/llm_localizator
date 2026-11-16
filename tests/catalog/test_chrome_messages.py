"""Chrome / WebExtension messages.json adapter (ADR-142)."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.catalog import build_catalog

EN = {
    "appName": {"message": "Demo", "description": "Name of the extension"},
    "greet": {"message": "Hello, $USER$! You owe $$5.", "description": "Greeting",
              "placeholders": {"user": {"content": "$1", "example": "Ann"}}},
}


def _cat(tmp_path: Path):
    en = tmp_path / "_locales" / "en"
    en.mkdir(parents=True)
    (en / "messages.json").write_text(json.dumps(EN, indent=4), encoding="utf-8")
    return build_catalog("chrome-messages", tmp_path, "_locales/{locale}/messages.json", "en")


def test_placeholders_become_icu_and_notes_travel(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    assert cat.load("en")["greet"] == "Hello, {user}! You owe $5."
    assert cat.load_entries("en")["greet"].note == "Greeting"


def test_target_save_copies_placeholders_and_keeps_indent(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    cat.save("pl", None, {"appName": "Demo", "greet": "Cześć, {user}! Jesteś winien $5."})
    raw = (tmp_path / "_locales" / "pl" / "messages.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["greet"]["message"] == "Cześć, $user$! Jesteś winien $$5."
    assert data["greet"]["placeholders"]["user"]["content"] == "$1"
    assert data["greet"]["description"] == "Greeting"
    cat.invalidate()
    assert cat.load("pl")["greet"].startswith("Cześć, {user}")


def test_regional_locale_directory_uses_underscore(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    cat.save("pt-BR", None, {"appName": "Demo"})
    assert (tmp_path / "_locales" / "pt_BR" / "messages.json").exists()
    assert "pt-BR" in cat.locales_present()


def test_resave_keeps_the_files_indent_and_content(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    cat.save("en", None, cat.load("en"))
    path = tmp_path / "_locales" / "en" / "messages.json"
    assert json.loads(path.read_text(encoding="utf-8")) == EN
    assert path.read_text(encoding="utf-8").startswith('{\n    "appName"')
