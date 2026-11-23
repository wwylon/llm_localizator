"""v65: Flet widgets and keyword text in GUI projects, JSON screen definitions, mkdocs site text."""

from __future__ import annotations

import json

from llm_localizator.scan.py_sinks import server_strings
from llm_localizator.scan.source import SourceScanner

FLET = '''
import flet as ft

def view(page):
    ft.Text("Serial Connection", size=16)
    ft.ElevatedButton("Scan Ports")
    ft.TextField(label="Port number", hint_text="Enter a port")
    SettingField(label="Port", tooltip="Default is 7777.", default="7777")
    parser = ArgumentParser(description="A command line tool")
    Field(description="API docs only")
'''

CONFIG = {"pages": [{"widgets": [
    {"type": "spinbox", "name": "Cargo low", "label": "Low goals", "heading": "Scoring"},
    {"type": "radio", "name": "Climb", "options": ["None", "Low", "High"], "label": "Climb level"},
    {"type": "text", "name": "Notes", "placeholder": "Anything else?"},
]}]}

MKDOCS = (
    "site_name: My Docs\nsite_description: Notes about things\nnav:\n  - Home: index.md\n"
    "  - User guide:\n    - Install: install.md\ntheme:\n  name: material\n"
)


def test_flet_widgets_and_keyword_text_are_found_but_argparse_and_field_docs_are_not() -> None:
    found = {s.text for s in server_strings(FLET)}
    assert {"Serial Connection", "Scan Ports", "Port number", "Enter a port", "Port", "Default is 7777."} <= found
    assert "A command line tool" not in found and "API docs only" not in found
    assert "7777" not in found


def test_a_json_screen_definition_is_read_but_a_plain_data_file_is_not(tmp_path) -> None:
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "config.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    (tmp_path / "public" / "data.json").write_text(json.dumps({"label": "one", "id": 3}), encoding="utf-8")
    hits = SourceScanner(tmp_path, ["."]).scan().hardcoded
    texts = {h.text for h in hits if h.file == "public/config.json"}
    assert {"Low goals", "Scoring", "Climb level", "Anything else?", "High"} <= texts
    assert not [h for h in hits if h.file == "public/data.json"]


def test_translation_catalogues_in_a_locales_folder_are_not_ui_config(tmp_path) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    assert not [h for h in SourceScanner(tmp_path, ["."]).scan().hardcoded if h.file.startswith("locales/")]


def test_mkdocs_site_name_description_and_navigation_labels_are_found(tmp_path) -> None:
    (tmp_path / "mkdocs.yml").write_text(MKDOCS, encoding="utf-8")
    texts = {h.text for h in SourceScanner(tmp_path, ["."]).scan().hardcoded}
    assert {"My Docs", "Notes about things", "Home", "User guide", "Install"} <= texts
    assert "material" not in texts and "index.md" not in texts
