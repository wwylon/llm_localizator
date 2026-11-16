"""Literal-language scan. One hit and one miss per language."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.scan import build_scanner

_FILES = {
    "typescript": (
        "label.ts",
        '// Please ignore this sentence\nconst label = "Please sign in now";\nconst id = "Bridge";\n',
    ),
    "go": (
        "main.go",
        '// Please ignore this sentence\npackage p\nfunc f() {\n    msg := "Please sign in now"\n    name := "Bridge"\n}\n',
    ),
    "cpp": (
        "main.cpp",
        '// Please ignore this sentence\nconst char* s = "Please sign in now";\nconst char* id = "Bridge";\n',
    ),
    "python": (
        "app.py",
        '"""Please ignore this module sentence."""\ndef f():\n    return "Please sign in now"\n# Please ignore this sentence\nx = "Bridge"\n',
    ),
    "csharp": (
        "App.cs",
        '// Please ignore this sentence\nclass C {\n    string s = "Please sign in now";\n    string id = "Bridge";\n}\n',
    ),
    "php": (
        "page.php",
        "<p>Please sign in now</p>\n<?php\n// Please ignore this sentence\necho \"Bridge\";\n",
    ),
    "swift": (
        "View.swift",
        '// Please ignore this sentence\nlet label = "Please sign in now"\nlet id = "Bridge"\n',
    ),
    "objc": (
        "View.m",
        '// Please ignore this sentence\nNSString *s = @"Please sign in now";\nNSString *i = @"Bridge";\n',
    ),
    "java": (
        "Activity.java",
        '// Please ignore this sentence\nString s = "Please sign in now";\nString id = "Bridge";\n',
    ),
    "kotlin": (
        "Main.kt",
        '// Please ignore this sentence\nval s = "Please sign in now"\nval id = "Bridge"\n',
    ),
    "dart": (
        "main.dart",
        '// Please ignore this sentence\nconst s = "Please sign in now";\nconst id = "Bridge";\n',
    ),
    "svelte": (
        "Widget.svelte",
        '<script>\n// Please ignore this sentence\nconst s = "Please sign in now";\nconst id = "Bridge";\n</script>\n',
    ),
}

_FILES["ruby"] = ("app.rb", '# Please ignore this sentence\nmsg = "Please sign in now"\nid = "Bridge"\n')
_FILES["rust"] = ("main.rs", '// Please ignore this sentence\nfn f() {\n    let msg = "Please sign in now";\n    let id = "Bridge";\n}\n')
_FILES["scala"] = ("App.scala", '// Please ignore this sentence\nval msg = "Please sign in now"\nval id = "Bridge"\n')
_FILES["lua"] = ("main.lua", '-- Please ignore this sentence\nlocal msg = "Please sign in now"\nlocal id = "Bridge"\n')
_FILES["elixir"] = ("app.ex", '# Please ignore this sentence\nmsg = "Please sign in now"\nid = "Bridge"\n')
_FILES["gdscript"] = ("main.gd", '# Please ignore this sentence\nvar msg = "Please sign in now"\nvar id = "Bridge"\n')

#: Single-file components have their own scanner (scan/sfc.py), not the literal detector.
_SFC = {"svelte", "vue"}
_FILES["vue"] = ("Widget.vue", _FILES["svelte"][1])


@pytest.mark.parametrize("language_id", sorted(_FILES))
def test_literal_language_hits_prose_and_skips_noise(tmp_path: Path, language_id: str) -> None:
    name, body = _FILES[language_id]
    src = tmp_path / "src"
    src.mkdir()
    (src / name).write_text(body, encoding="utf-8")
    result = build_scanner("source", tmp_path, ["src"]).scan()
    texts = [hit.text for hit in result.hardcoded]
    assert "Please sign in now" in texts
    assert not any("ignore" in text for text in texts)
    assert "Bridge" not in texts


def test_registry_languages_match_fixtures() -> None:
    from llm_localizator.core.languages import literal_languages

    assert {row.id for row in literal_languages()} == set(_FILES) - _SFC


def test_confidence_low_for_literal_language(tmp_path: Path) -> None:
    name, body = _FILES["python"]
    src = tmp_path / "src"
    src.mkdir()
    (src / name).write_text(body, encoding="utf-8")
    result = build_scanner("source", tmp_path, ["src"]).scan()
    prose_hits = [h for h in result.hardcoded if "Please sign in now" in h.text]
    assert prose_hits
    assert all(h.confidence == "low" for h in prose_hits)


def _scan_ts(tmp_path: Path, body: str):
    src = tmp_path / "src"
    src.mkdir()
    (src / "labels.ts").write_text(body, encoding="utf-8")
    return build_scanner("source", tmp_path, ["src"]).scan().hardcoded


def test_member_repeating_its_own_label_is_medium(tmp_path: Path) -> None:
    hits = _scan_ts(tmp_path, """export const L = {
  SAVE: "Save",
  saveChanges: "Save changes",
};
""")
    by_text = {h.text: h for h in hits}
    assert by_text["Save"].confidence == "medium"
    assert "member 'SAVE'" in by_text["Save"].reason
    assert by_text["Save changes"].confidence == "medium"


def test_member_with_a_different_value_or_comment_is_not_flagged(tmp_path: Path) -> None:
    hits = _scan_ts(tmp_path, """const a = { KIND: "primary" };
// SAVE: "Save"
const b = { url: "https" };
""")
    assert [h.text for h in hits] == []


def test_routed_member_is_skipped(tmp_path: Path) -> None:
    hits = _scan_ts(tmp_path, 'const L = { SAVE: t("Save") };\n')
    assert hits == []


def test_routed_call_does_not_hide_other_literals_on_the_line(tmp_path) -> None:
    from llm_localizator.scan.literals import _ROUTED_ARG

    line = 'alert("Please sign in now"); t("ok.key")'
    assert {m.group(2) for m in _ROUTED_ARG.finditer(line)} == {"ok.key"}
