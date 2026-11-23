"""v64: GUI-project exceptions and label tables, status helpers, Qt dialog statics, Java enum labels."""

from __future__ import annotations

import pytest

from llm_localizator.scan.ecosystems import _SINKS
from llm_localizator.scan.project_index import ProjectIndex
from llm_localizator.scan.py_sinks import server_strings

QT_MODULE = '''
from PyQt5.QtWidgets import QInputDialog, QFormLayout

LABELS = {"dol": "App", "elf": "App", "thm": "Theme"}
CONFIG = {"mode": "fast", "retries": 3}

def go(self, form):
    self.set_status("Splitting into chapters?")
    text, ok = QInputDialog.getText(self, "Add Prefix", "Prefix to add:")
    form.addRow("Find:", self.edit)
'''

PLAIN_MODULE = '''
LABELS = {"dol": "App", "elf": "App", "thm": "Theme"}

def go(self):
    self.set_status("Splitting into chapters?")
'''

RAISES = '''
def build():
    raise M4BError("Cover download failed for this book.")
    raise ValueError("Invalid timestamp value in this file.")
    raise M4BError("short")
'''


def _texts(source: str, **kw) -> set[str]:
    return {s.text for s in server_strings(source, **kw)}


def test_qt_module_gets_status_helpers_dialog_statics_form_rows_and_label_tables() -> None:
    texts = _texts(QT_MODULE)
    assert {"Splitting into chapters?", "Add Prefix", "Prefix to add:", "Find:", "App", "Theme"} <= texts
    assert "fast" not in texts   # a settings dict is not a label table


def test_a_module_without_a_gui_toolkit_gets_none_of_it() -> None:
    assert not _texts(PLAIN_MODULE)


def test_project_defined_errors_with_a_sentence_are_screen_copy_only_in_gui_projects() -> None:
    assert "Cover download failed for this book." in _texts(RAISES, gui_project=True)
    assert "Cover download failed for this book." not in _texts(RAISES, gui_project=False)
    assert "Invalid timestamp value in this file." not in _texts(RAISES, gui_project=True)   # builtin error
    assert "short" not in _texts(RAISES, gui_project=True)


def test_project_index_knows_a_gui_project_from_its_requirements_or_its_imports(tmp_path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "requirements.txt").write_text("PyQt5==5.15\nrequests\n", encoding="utf-8")
    assert ProjectIndex(tmp_path / "a").py_gui
    (tmp_path / "b" / "app").mkdir(parents=True)
    (tmp_path / "b" / "app" / "main.py").write_text("import tkinter as tk\n", encoding="utf-8")
    assert ProjectIndex(tmp_path / "b").py_gui
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "tool.py").write_text("import json\n", encoding="utf-8")
    assert not ProjectIndex(tmp_path / "c").py_gui


@pytest.mark.parametrize("line", [
    'NONE("None", "Don\'t compress"),',
    "    BEST(\"Best\", 9);",
    'HBox w = getDirectorySelectWidget(dir, "Choose memo directory", null);',
    'try (var task = monitor.begin("Export tracks", n)) {',
])
def test_java_enum_labels_widget_factories_and_monitor_names_are_sinks(line: str) -> None:
    assert _SINKS["java"].search(line)


@pytest.mark.parametrize("line", [
    'String type = response.getHeader("Content-Type");',
    'int MAX_SIZE = 5;',
    'logger.info("starting");',
])
def test_java_headers_constants_and_logging_are_not_sinks(line: str) -> None:
    assert not _SINKS["java"].search(line)
