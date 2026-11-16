"""scan/locate.py and scan/usage_calls.py (ADR-120)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan import js_context
from llm_localizator.scan.locate import LiteralIndex, normalize_text, source_files
from llm_localizator.scan.usage_calls import ROUTED_CALLS, KeyUsage, collect_key_usage


class _Cfg:
    def __init__(self, root: Path, src_dirs: list[str]) -> None:
        self.root = root
        self.scan_src_dirs = src_dirs
        self.scan_exclude: list[str] = []
        self.scan_unskip: list[str] = []


def _project(tmp_path: Path) -> _Cfg:
    web = tmp_path / "web"
    (web / "node_modules" / "x").mkdir(parents=True)
    (web / "app.js").write_text(
        "const a = 1;\nel.textContent = 'Save &amp; close';\n"
        "const msg = `Showing\n   all   rows`;\n", encoding="utf-8")
    (web / "index.html").write_text("<p>Hardcoded footer</p>\n", encoding="utf-8")
    (web / "vendor.min.js").write_text("var x='Bundle text';\n", encoding="utf-8")
    (web / "node_modules" / "x" / "lib.js").write_text("'Library text'\n", encoding="utf-8")
    return _Cfg(tmp_path, ["web"])


def test_source_files_skip_bundles_and_dependencies(tmp_path: Path) -> None:
    names = sorted(p.name for p in source_files(_project(tmp_path)))
    assert names == ["app.js", "index.html"]


def test_literal_index_finds_file_and_line(tmp_path: Path) -> None:
    index = LiteralIndex(_project(tmp_path))
    hit = index.find("Hardcoded footer")
    assert (hit.file, hit.line) == ("web/index.html", 1)
    # Entities and whitespace normalise the same way the page renders them.
    assert index.find("Save & close").line == 2
    assert index.find("Showing all rows").line == 3
    assert index.find("Server says hello") is None
    assert not index.is_literal("Bundle text")
    assert index.is_literal("  ")


def test_long_text_matches_on_its_prefix(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    (tmp_path / "web" / "long.js").write_text(
        "const s = 'A long sentence that continues well past forty characters ' + n;\n",
        encoding="utf-8")
    index = LiteralIndex(cfg)
    assert index.find("A long sentence that continues well past forty characters 3 more").file == "web/long.js"


def test_normalize_text() -> None:
    assert normalize_text("  Save &amp;\n Close ") == "save & close"


def test_key_usage_extraction() -> None:
    usage = KeyUsage()
    collect_key_usage(
        "/* i18n.t('doc.example') */\n"
        "uiT('ui.save'); i18n.t('nav.home'); t('plain'); t('a.b');\n"
        "i18n.t(`kind.${k}`); i18n.t('pre.' + x); i18n.t(name);\n"
        '<b data-i18n-aria-label="x.aria"></b>\n', "f.js", usage)
    assert set(usage.keys) == {"ui.save", "nav.home", "a.b", "x.aria"}
    assert usage.prefixes == {"kind.", "pre."}
    assert usage.dynamic == ["f.js:3"]
    assert usage.covers("kind.image") and not usage.covers("other")


def test_scanner_uses_the_shared_routed_list() -> None:
    assert js_context.ROUTED_CALLS is ROUTED_CALLS
