"""v68: regex patterns and language catalogues are developer text; Java output-pane helpers are screen text."""

from __future__ import annotations

from llm_localizator.scan.py_sinks import dev_strings
from llm_localizator.scan.source import SourceScanner

PY = '''import re

TEXT = {
    "en": {"title": "Persian OCR", "run": "Run OCR"},
    "fa": {"title": "OCR فارسی", "run": "اجرای OCR"},
}

_FIXES = [
    (re.compile(r"قدر +تمند"), "قدرتمند"),
]
'''

JAVA = """package app;

public class Kmp {
    void run() {
        appendProgress("Building LPS array...");
        showAlertDialog("Pattern is empty");
    }
}
"""


def _texts(source: str) -> set[str]:
    return {text for _line, text in dev_strings(source)}


def test_a_language_keyed_catalogue_and_regex_pairs_are_developer_text() -> None:
    texts = _texts(PY)
    assert {"Persian OCR", "Run OCR", "قدرتمند"} <= texts


def test_a_dict_that_is_not_keyed_by_language_stays_screen_text() -> None:
    source = 'LABELS = {"open": {"x": "Open file"}, "save": {"x": "Save file"}}\n'
    assert not _texts(source)


def test_java_output_pane_and_alert_helpers_are_found(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Kmp.java").write_text(JAVA, encoding="utf-8")
    texts = {h.text for h in SourceScanner(tmp_path, ["."]).scan().hardcoded if h.confidence in ("high", "medium")}
    assert {"Building LPS array...", "Pattern is empty"} <= texts
