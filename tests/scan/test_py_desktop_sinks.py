"""Python desktop GUI captions (Tk, Qt, wx) are found, and only in modules that import a GUI toolkit."""

from __future__ import annotations

from llm_localizator.scan.py_sinks import server_strings

TK = '''
import tkinter as tk
from tkinter import ttk

root = tk.Tk()
root.title("Data Explorer")
menu = tk.Menu(root)
menu.add_cascade(label="Edit", menu=menu)
menu.add_command(label="Select All", command=None)
ttk.Button(root, text="Apply").pack()
tk.Label(root, text="Number of rows:").pack()
labels = ("Frequency", "Periods")
dlg = make_dialog(root, labels=("Start date", "End date"))
state = {"label": "log y", "kind": "line"}
'''

QT = '''
from PyQt5.QtWidgets import QPushButton, QAction, QLabel

button = QPushButton("Cancel")
action = QAction("Open file", parent)
label = QLabel("Choose a folder")
window.setWindowTitle("Converter")
edit.setPlaceholderText("Search")
box.addItems(["Fast", "Slow"])
print("debug output here")
'''


def _by_text(source: str) -> dict[str, str]:
    return {s.text: s.sink for s in server_strings(source)}


def test_tk_captions_are_found() -> None:
    found = _by_text(TK)
    for text in ("Data Explorer", "Edit", "Select All", "Apply", "Number of rows:", "Start date", "End date", "log y"):
        assert text in found, text
    assert found["Apply"].startswith("desktop:")


def test_qt_captions_are_found_but_log_output_is_not() -> None:
    found = _by_text(QT)
    for text in ("Cancel", "Open file", "Choose a folder", "Converter", "Search", "Fast", "Slow"):
        assert text in found, text
    assert "debug output here" not in found


def test_nothing_is_found_in_a_module_without_a_gui_toolkit() -> None:
    plain = 'class Page:\n    def render(self):\n        return Button("Apply", text="Hello there")\n'
    assert not [s for s in server_strings(plain) if s.sink.startswith("desktop:")]


def test_one_file_that_breaks_the_scanner_is_skipped_not_fatal(tmp_path) -> None:
    from llm_localizator.scan.base import ScanResult, scan_file_hits

    class Scanner:
        root = tmp_path

        def scan_file(self, path, lines, result) -> None:
            raise RuntimeError("lexer bug")

    src = tmp_path / "app.py"
    src.write_text("x = 1\n", encoding="utf-8")
    result = ScanResult()
    assert scan_file_hits(Scanner(), src, result) == []
    assert any("scan error (RuntimeError)" in item for item in result.skipped)
