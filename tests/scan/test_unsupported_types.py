"""File types the scanner cannot read are reported, never silently skipped."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan import build_scanner
from llm_localizator.scan.base import count_unsupported


def test_unsupported_ui_file_types_are_counted(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pug").write_text("<h1>Welcome back</h1>\n", encoding="utf-8")
    (src / "b.pug").write_text("<h1>Hello there</h1>\n", encoding="utf-8")
    (src / "c.groovy").write_text("<p>Save changes</p>\n", encoding="utf-8")
    (src / "d.js").write_text("const x = 1;\n", encoding="utf-8")
    scanner = build_scanner("source", tmp_path, ["src"])
    assert count_unsupported(scanner) == {".pug": 2, ".groovy": 1}


def test_supported_only_project_reports_nothing(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "App.vue").write_text("<template><p>Hello</p></template>\n", encoding="utf-8")
    assert count_unsupported(build_scanner("source", tmp_path, ["src"])) == {}
