"""doctor [scan] warnings (M6): missing src_dirs, unread file types, Xcode targets without the catalogue."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.doctor import scan_checks
from llm_localizator.projects import load_config


def _cfg(tmp_path: Path, scan: str):
    (tmp_path / ".llm-localize.toml").write_text(f'[project]\nname = "ex"\n{scan}', encoding="utf-8")
    return load_config(tmp_path / ".llm-localize.toml")


def test_no_scan_section_means_no_scan_checks(tmp_path: Path) -> None:
    assert scan_checks(_cfg(tmp_path, "")) == []


def test_missing_src_dir_and_unread_types_warn(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text('x = "Hello there"\n', encoding="utf-8")
    (tmp_path / "src" / "about.pug").write_text("p Hello there\n", encoding="utf-8")
    checks = scan_checks(_cfg(tmp_path, '[scan]\nadapter = "source"\nsrc_dirs = ["src", "web"]\n'))
    details = " | ".join(c.detail for c in checks)
    assert all(c.status == "warn" for c in checks)
    assert "src_dirs not found: web" in details
    assert "NOT scanned: .pug (1)" in details


def test_clean_scan_config_is_ok(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text('x = "Hello there"\n', encoding="utf-8")
    checks = scan_checks(_cfg(tmp_path, '[scan]\nadapter = "source"\nsrc_dirs = ["src"]\n'))
    assert [c.status for c in checks] == ["ok"]


_PBX = """
AAAAAAAAAAAAAAAAAAAAAAA1 /* App.swift in Sources */ = {isa = PBXBuildFile; };
AAAAAAAAAAAAAAAAAAAAAAA2 /* Widget.swift in Sources */ = {isa = PBXBuildFile; };
AAAAAAAAAAAAAAAAAAAAAAA3 /* Localizable.strings in Resources */ = {isa = PBXBuildFile; };
BBBBBBBBBBBBBBBBBBBBBBB1 /* Sources */ = {
    isa = PBXSourcesBuildPhase;
    files = (AAAAAAAAAAAAAAAAAAAAAAA1);
};
BBBBBBBBBBBBBBBBBBBBBBB2 /* Resources */ = {
    isa = PBXResourcesBuildPhase;
    files = (AAAAAAAAAAAAAAAAAAAAAAA3);
};
BBBBBBBBBBBBBBBBBBBBBBB3 /* Sources */ = {
    isa = PBXSourcesBuildPhase;
    files = (AAAAAAAAAAAAAAAAAAAAAAA2);
};
CCCCCCCCCCCCCCCCCCCCCCC1 /* MyApp */ = {
    isa = PBXNativeTarget;
    buildPhases = (BBBBBBBBBBBBBBBBBBBBBBB1, BBBBBBBBBBBBBBBBBBBBBBB2);
};
CCCCCCCCCCCCCCCCCCCCCCC2 /* MyWidget */ = {
    isa = PBXNativeTarget;
    buildPhases = (BBBBBBBBBBBBBBBBBBBBBBB3);
};
"""


def test_xcode_target_without_catalogue_warns(tmp_path: Path) -> None:
    (tmp_path / "App").mkdir()
    (tmp_path / "App" / "App.swift").write_text('Text("Hello")\n', encoding="utf-8")
    (tmp_path / "App" / "Localizable.strings").write_text('"Hello" = "Hello";\n', encoding="utf-8")
    (tmp_path / "App.xcodeproj").mkdir()
    (tmp_path / "App.xcodeproj" / "project.pbxproj").write_text(_PBX, encoding="utf-8")
    checks = scan_checks(_cfg(tmp_path, '[scan]\nadapter = "source"\nsrc_dirs = ["App"]\n'))
    xcode = [c for c in checks if "Xcode" in c.detail]
    assert xcode and "MyWidget" in xcode[0].detail and "MyApp" not in xcode[0].detail
