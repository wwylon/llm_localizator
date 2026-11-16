"""Contract tests over every catalogue adapter (review 20.1, 20.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.catalog import build_catalog

FORMATS = {
    "json-nested": "{locale}/{namespace}.json",
    "json-flat": "{locale}/{namespace}.json",
    "yaml": "{locale}/{namespace}.yml",
    "po": "{locale}/{namespace}.po",
    "arb": "{locale}/{namespace}.arb",
    "android-xml": "values-{locale}/{namespace}.xml",
    "multilang-json": "{namespace}.json",
    "csv": "{namespace}.csv",
    "php-array": "{locale}/{namespace}.php",
    "go-i18n": "{locale}/{namespace}.json",
    "ios-strings": "{locale}.lproj/{namespace}.strings",
    "properties": "{namespace}_{locale}.properties",
    "resx": "{namespace}.{locale}.resx",
    "qt-ts": "{namespace}_{locale}.ts",
    "chrome-messages": "_locales/{locale}/{namespace}.json",
}

DATA = {"greet": "Hello", "bye": "Goodbye, {name}", "quote": 'Say "hi"', "multi": "a\nb"}


def _cat(fmt: str, root: Path):
    return build_catalog(fmt, root, FORMATS[fmt], "en")


@pytest.mark.parametrize("fmt", sorted(FORMATS))
def test_save_load_save_is_idempotent(fmt: str, tmp_path: Path) -> None:
    cat = _cat(fmt, tmp_path)
    cat.save("en", "app", dict(DATA))
    first = cat.load("en", "app")
    assert first == DATA
    path = cat.path_for("en", "app") if hasattr(cat, "path_for") else None
    cat.save("en", "app", first)
    assert cat.load("en", "app") == DATA
    if path is not None and Path(path).is_file():
        before = Path(path).read_bytes()
        cat.save("en", "app", cat.load("en", "app"))
        assert Path(path).read_bytes() == before


@pytest.mark.parametrize("fmt", sorted(FORMATS))
def test_save_touches_only_its_own_locale(fmt: str, tmp_path: Path) -> None:
    """``save`` replaces one locale's file/column; other locales are untouched.

    Callers pass the full merged key set (``merge_for_write``). Shared-file
    formats (CSV / multilang-json) prune keys absent from that set.
    """
    cat = _cat(fmt, tmp_path)
    cat.save("en", "app", dict(DATA))
    pl_keys = {"greet": "Czesc", "bye": "Do widzenia", "quote": 'Powiedz "czesc"', "multi": "a\nb"}
    cat.save("pl", "app", pl_keys)
    cat.save("de", "app", {**pl_keys, "greet": "Hallo"})
    assert cat.load("pl", "app")["greet"] == "Czesc"
    assert cat.load("pl", "app")["bye"] == "Do widzenia"
    assert cat.load("en", "app") == DATA


@pytest.mark.parametrize("fmt", ["po", "csv", "multilang-json", "json-nested"])
def test_merge_then_save_drops_orphan_keys(fmt: str, tmp_path: Path) -> None:
    """Orphans absent from source must not survive ``merge_for_write`` + ``save``."""
    cat = _cat(fmt, tmp_path)
    cat.save("en", "app", {"greet": "Hello", "gone": "Obsolete"})
    cat.save("pl", "app", {"greet": "Czesc", "gone": "Przestarzale"})
    source = {"greet": "Hello"}
    existing = cat.load("pl", "app")
    merged = cat.merge_for_write(source, existing, {})
    assert "gone" not in merged
    cat.save("pl", "app", merged)
    assert "gone" not in cat.load("pl", "app")
    assert cat.load("pl", "app").get("greet") == "Czesc"


def test_android_keeps_exact_plural_branches(tmp_path: Path) -> None:
    cat = _cat("android-xml", tmp_path)
    msg = "{n, plural, =0 {No items} one {# item} other {# items}}"
    cat.save("en", "app", {"items": msg})
    got = cat.load("en", "app")["items"]
    assert "=0 {No items}" in got and "one {# item}" in got and "other {# items}" in got
    cat.save("en", "app", {"items": got})
    assert cat.load("en", "app")["items"] == got


def test_android_notes_multiline_and_trailing(tmp_path: Path) -> None:
    (tmp_path / "values-en").mkdir()
    (tmp_path / "values-en" / "app.xml").write_text(
        '<resources>\n'
        '    <!-- first line\n       second line -->\n'
        '    <string name="a">A</string>\n'
        '    <string name="b">B</string> <!-- trailing note -->\n'
        '    <string name="c">C</string>\n'
        '</resources>\n',
        encoding="utf-8",
    )
    entries = _cat("android-xml", tmp_path).load_entries("en", "app")
    assert entries["a"].note == "first line second line"
    assert entries["b"].note == "trailing note"
    assert entries["c"].note == ""


@pytest.mark.parametrize("fmt,text", [
    ("properties", "# note\nkey=v\n"),
    ("ios-strings", '/* note */\n"key" = "v";\n'),
    ("php-array", "<?php\nreturn [\n    // note\n    'key' => 'v',\n];\n"),
    ("android-xml", "<resources><!-- note --><string name=\"key\">v</string></resources>"),
])
def test_whole_file_rewrite_warns_once_about_comments(fmt: str, text: str, tmp_path: Path) -> None:
    cat = _cat(fmt, tmp_path)
    path = cat.path_for("en", "app")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    with pytest.warns(UserWarning, match="comments are not preserved"):
        cat.save("en", "app", {"key": "v"})
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        cat.save("en", "app", {"key": "v"})  # second save: silent
