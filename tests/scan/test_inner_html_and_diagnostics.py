from __future__ import annotations

from llm_localizator.scan.base import ScanResult
from llm_localizator.scan.raw_js import RawJsScanner


def test_inner_html_template_literal_is_detected(tmp_path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.js").write_text(
        'el.innerHTML = `<button>Please sign in</button>`;\n',
        encoding="utf-8",
    )
    scanner = RawJsScanner(tmp_path, ["src"])
    result = scanner.scan()
    texts = [h.text for h in result.hardcoded]
    assert any("Please sign in" in t for t in texts)


def test_unreadable_files_are_reported(tmp_path) -> None:
    result = ScanResult()
    result.unreadable.append("src/x.bin: UnicodeDecodeError")
    diag = result.diagnostics()
    assert diag["unreadableCount"] == 1
    assert diag["filesScanned"] == 0


def test_mixed_routed_line_reports_the_unrouted_part(tmp_path) -> None:
    """The literal pass judges each literal, so an i18n.t() call on the line no
    longer hides prose beside it (the old line-level trade-off)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.js").write_text(
        'btn.innerHTML = i18n.t("save") + ` Also hardcoded text here`;\n',
        encoding="utf-8",
    )
    scanner = RawJsScanner(tmp_path, ["src"])
    result = scanner.scan()
    assert any("Also hardcoded" in h.text for h in result.hardcoded)
    assert not any(h.text == "save" for h in result.hardcoded)
