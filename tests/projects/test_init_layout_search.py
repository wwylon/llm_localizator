"""Fallback catalogue search for layouts outside KNOWN_LAYOUTS (V-001)."""

from __future__ import annotations

import json

from llm_localizator.projects.init_layout import detect_layout


def _json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_nested_json_next_to_sibling_locales(tmp_path):
    base = tmp_path / "packages" / "app" / "locales"
    _json(base / "en.json", {"labels": {"ok": "OK"}})
    _json(base / "pl.json", {"labels": {"ok": "OK"}})
    assert detect_layout(tmp_path) == ("json-nested", "packages/app/locales/{locale}.json", None)


def test_flat_json_at_top_level_dir(tmp_path):
    _json(tmp_path / "i18n" / "en.json", {"a.b": "x"})
    _json(tmp_path / "i18n" / "de.json", {"a.b": "y"})
    assert detect_layout(tmp_path)[:2] == ("json-flat", "i18n/{locale}.json")


def test_gettext_nested_conf_dir(tmp_path):
    for loc in ("en", "pl", "de"):
        d = tmp_path / "pkg" / "conf" / "locale" / loc / "LC_MESSAGES"
        d.mkdir(parents=True)
        (d / "app.po").write_text('msgid "a"\nmsgstr "a"\n', encoding="utf-8")
    fmt, template, _ = detect_layout(tmp_path)
    assert (fmt, template) == ("po", "pkg/conf/locale/{locale}/LC_MESSAGES/{namespace}.po")


def test_test_fixtures_and_lone_files_ignored(tmp_path):
    _json(tmp_path / "tests" / "locales" / "en.json", {"a": "x"})
    _json(tmp_path / "tests" / "locales" / "pl.json", {"a": "y"})
    _json(tmp_path / "config" / "en.json", {"a": "x"})  # no sibling locale
    assert detect_layout(tmp_path) is None


def test_most_siblings_wins(tmp_path):
    for loc in ("en", "pl"):
        _json(tmp_path / "a" / f"{loc}.json", {"k": "v"})
    for loc in ("en", "pl", "de", "fr"):
        _json(tmp_path / "zz" / "deep" / f"{loc}.json", {"k": "v"})
    assert detect_layout(tmp_path)[1] == "zz/deep/{locale}.json"


def test_chrome_messages_layout(tmp_path):
    for loc in ("en", "pl"):
        _json(tmp_path / "_locales" / loc / "messages.json", {
            "appName": {"message": "Demo", "description": "name"},
        })
    assert detect_layout(tmp_path) == (
        "chrome-messages", "_locales/{locale}/messages.json", None,
    )


def test_qt_ts_layout(tmp_path):
    for loc in ("en", "pl"):
        path = tmp_path / "translations" / f"app_{loc}.ts"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '<?xml version="1.0"?><TS><context><name>App</name>'
            '<message><source>Hi</source><translation>Hi</translation></message>'
            "</context></TS>\n",
            encoding="utf-8",
        )
    assert detect_layout(tmp_path)[:2] == ("qt-ts", "translations/app_{locale}.ts")
