"""v62: Qt translate and message boxes, Java status helpers and file filters, text resources in ``text/`` folders."""

from __future__ import annotations

import pytest

from llm_localizator.scan.ecosystems import _SINKS
from llm_localizator.scan.py_sinks import server_strings
from llm_localizator.scan.source import SourceScanner

PY = '''
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QMessageBox
from tkinter import messagebox
import logging

Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"Download - Select Location", None))
QMessageBox.warning(self, 'Invalid IP Address', 'This IP address is invalid.')
messagebox.showerror("Save failed", "Could not write the file")
self.show_success("Saved all changes")
logging.warning("disk almost full here")
'''


def test_python_qt_translate_message_boxes_and_helpers_are_found_but_logging_is_not() -> None:
    found = {s.text for s in server_strings(PY)}
    assert {
        "Download - Select Location", "Invalid IP Address", "This IP address is invalid.",
        "Save failed", "Could not write the file", "Saved all changes",
    } <= found
    assert "disk almost full here" not in found


@pytest.mark.parametrize("line", [
    'updateStatus("Startup complete");',
    'showStatus("Card inserted.");',
    'UIUtils.showErrorDialog(e, "Cannot save");',
    'chooser.setDialogTitle("Save tracks to");',
    'chooser.addChoosableFileFilter(new FileExtensionFilter("OGG Files", "ogg"));',
    'new FileChooser.ExtensionFilter("CSV Files", "*.csv")',
    'settings.setBorder(new LabeledBorder("Settings"));',
    'sendError("No input stream", CODE);',
])
def test_java_status_helpers_filters_and_borders_are_sinks(line: str) -> None:
    assert _SINKS["java"].search(line)


def test_text_resources_in_a_text_folder_are_scanned_but_other_txt_files_are_not(tmp_path) -> None:
    (tmp_path / "res" / "text").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    prose = "Pick the folder where exported sprites are saved. Existing files are never overwritten.\n"
    (tmp_path / "res" / "text" / "tip.txt").write_text(prose, encoding="utf-8")
    (tmp_path / "docs" / "notes.txt").write_text(prose, encoding="utf-8")
    result = SourceScanner(tmp_path, ["."]).scan()
    files = {hit.file for hit in result.hardcoded}
    assert "res/text/tip.txt" in files
    assert "docs/notes.txt" not in files
