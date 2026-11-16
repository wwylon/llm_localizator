"""Scanner must stay linear on hostile real-world input (bench prerequisite)."""

from __future__ import annotations

import time
from pathlib import Path

from llm_localizator.scan.base import ScanResult, is_minified, line_number, read_source_lines
from llm_localizator.scan.literals import _ROUTED_ARG
from llm_localizator.scan.raw_js import RawJsScanner, _balanced_call_inner


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def test_routed_arg_regex_does_not_backtrack_on_unterminated_call() -> None:
    line = 't("' + "." * 40
    assert _timed(lambda: list(_ROUTED_ARG.finditer(line))) < 0.5


def test_routed_arg_accepts_escaped_quote() -> None:
    match = _ROUTED_ARG.search(r"t('don\'t save')")
    assert match is not None and match.group(2) == r"don\'t save"


def test_unbalanced_helper_calls_stay_linear(tmp_path: Path) -> None:
    src = tmp_path / "app.js"
    src.write_text("card(\"Open file\", x\n" * 2000, encoding="utf-8")
    scanner = RawJsScanner(tmp_path, ["."])
    assert _timed(scanner.scan) < 5.0


def test_balanced_call_skips_template_literals_and_comments() -> None:
    text = 'card(`a ) b`, /* ) */ "Title") tail'
    parsed = _balanced_call_inner(text, text.index("("))
    assert parsed is not None
    assert parsed[0] == '`a ) b`, /* ) */ "Title"'


def test_line_number_matches_newline_count() -> None:
    text = "a\nbb\n\nccc\n"
    for index in range(len(text) + 1):
        assert line_number(text, index) == text.count("\n", 0, index) + 1


def test_minified_bundle_is_skipped(tmp_path: Path) -> None:
    bundle = tmp_path / "support.js"
    bundle.write_text('var a="Hello world";' * 500, encoding="utf-8")
    result = ScanResult()
    assert read_source_lines(bundle, result, "support.js") is None
    assert result.skipped == ["support.js: minified"]
    # One long data line in an ordinary file is not a bundle.
    assert not is_minified(["const label = 'Save';"] * 40 + ["x" * 2500])


def test_non_utf8_file_is_scanned_with_replacement(tmp_path: Path) -> None:
    src = tmp_path / "page.html"
    src.write_bytes("<p>Caf\xe9 is open today</p>\n".encode("latin-1"))
    result = RawJsScanner(tmp_path, ["."]).scan()
    assert result.decode_fallback == 1
    assert any("is open today" in hit.text for hit in result.hardcoded)
