"""Dashboard and editor. Coverage comes from the API. Plurals stay one value."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from llm_localizator.catalog.export_formats import render_export
from llm_localizator.catalog.history import HistoryStore
from llm_localizator.core.plurals import parse_icu_plural
from llm_localizator.web import build_state
from llm_localizator.web.plurals import joined_value, plural_view
from llm_localizator.web.server import (
    message_row,
    overview_stats,
    posted_translation,
    save,
    validate_key,
)
from llm_localizator.web.shell import render_shell

from .conftest import setup_project, write_json

PLURAL = "{n, plural, one {# file} other {# files}}"
STATIC = Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static"


def test_dashboard_html_does_not_bake_coverage(tmp_path: Path, make_config) -> None:
    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    write_json(tmp_path / "messages" / "de" / "app.json", {})
    app = build_state(make_config(tmp_path, targets=["pl", "de"]))
    stats = overview_stats(app)
    assert len(stats["locales"]) == 2
    html = render_shell("dashboard")
    js = (STATIC / "dashboard.js").read_text(encoding="utf-8")
    assert "/api/overview-lite" in js
    assert "/api/overview-stats" in js
    assert "count-kicker" in js
    assert "dash-grid" in js
    assert "frozen-badge" in js
    assert "quality-hist" in js
    assert 'id="dash-title"' in html
    assert 'id="review-badge"' in html
    assert 'href="/en/app/operations"' in html  # ADR-108 UI locale prefix
    assert 'id="dash-add-locale"' in html
    shell_js = (STATIC / "shell.js").read_text(encoding="utf-8")
    assert "locale-pick" in shell_js  # shared picker moved to shell.js
    assert "window.localePicker" in js  # dashboard delegates to shared picker
    assert "window.prompt" not in js
    assert 'href="/landing"' not in html
    for row in stats["locales"]:
        assert f'{row["coverage"]}%' not in html


def test_plural_fields_follow_the_active_standard() -> None:
    view = plural_view(PLURAL, "", "pl", "icu")
    assert view is not None
    assert view["categories"] == ["one", "few", "many", "other"]
    assert plural_view("Hello", "Cześć", "pl", "icu") is None
    assert plural_view(PLURAL, "", "pl", "i18next") is None
    assert joined_value("Hello", {"one": "x"}, {}, "icu") is None


def test_plural_save_round_trips_one_string(tmp_path: Path, make_config) -> None:
    setup_project(tmp_path, {"greet": "Hello", "count": PLURAL}, existing={"greet": "Witaj"})
    app = build_state(make_config(tmp_path))
    row = message_row(app, ["pl"], "app", "count")["row"]
    assert row["plural"]["categories"] == ["one", "few", "many", "other"]
    assert message_row(app, ["pl"], "app", "greet")["row"]["plural"] is None

    branches = {"one": "jeden plik", "few": "kilka plików", "many": "wiele plików", "other": "pliki"}
    value = posted_translation(app, "app", "count", {
        "pluralBranches": branches,
        "pluralVariable": row["plural"]["variable"],
        "pluralPrefix": row["plural"]["prefix"],
        "pluralSuffix": row["plural"]["suffix"],
    })
    assert value.count("{") == 1 or "plural" in value
    parsed_before_save = parse_icu_plural(value)
    assert parsed_before_save is not None
    assert set(parsed_before_save.branches) == set(branches)
    result = save(app, "pl", "app", "count", value)
    assert result["ok"] is True, result
    stored = app.catalog.load("pl", "app")["count"]
    parsed = parse_icu_plural(stored)
    assert parsed is not None
    assert parsed.branches["one"] == "jeden plik"
    assert parsed.branches["few"] == "kilka plików"
    assert parsed.branches["many"] == "wiele plików"
    assert parsed.branches["other"] == "pliki"
    assert set(app.catalog.load("pl", "app")) == {"greet", "count"}
    from llm_localizator.catalog import StateStore
    entry = StateStore(app.cfg.state_dir).entry("pl", "app", "count")
    assert entry["provider"] == "human"
    events = HistoryStore(app.cfg.history_root()).events_for("pl", "app", "count")
    assert events
    assert events[-1].next == stored


def test_validate_key_shows_a_dropped_placeholder_then_clears(tmp_path: Path, make_config) -> None:
    setup_project(tmp_path, {"greet": "Hello {name}"}, existing={"greet": "Witaj {name}"})
    app = build_state(make_config(tmp_path))
    dropped = validate_key(app, "pl", "app", "greet", "Witaj")
    assert dropped["ok"] is False
    assert dropped["errors"]
    restored = validate_key(app, "pl", "app", "greet", "Witaj {name}")
    assert restored["ok"] is True
    assert restored["errors"] == []


def test_export_keeps_only_the_selected_keys(tmp_path: Path, make_config) -> None:
    setup_project(
        tmp_path,
        {"greet": "Hello", "bye": "Goodbye"},
        existing={"greet": "Witaj", "bye": "Do widzenia"},
    )
    app = build_state(make_config(tmp_path))
    payload, _, _, _ = render_export(
        app.cfg, app.catalog, locales=["pl"], keys=["app.greet"],
    )
    text = payload.decode("utf-8")
    assert "greet" in text
    assert "bye" not in text
    assert "Do widzenia" not in text


def test_editor_search_and_bulk_keys() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    editor = STATIC / "editor.js"
    script = r"""
const fs = require("fs");
global.window = global;
global.document = undefined;
eval(fs.readFileSync(process.argv[1], "utf8"));
const api = global.llmEditor;
if (!api) { console.error("llmEditor missing"); process.exit(1); }
if (!api.regexpError("[")) process.exit(2);
if (api.regexpError("a+") !== "") process.exit(3);
const body = api.translateBody("demo", "pl", ["app.greet"]);
if (JSON.stringify(body.keys) !== JSON.stringify(["app.greet"])) {
  console.error(JSON.stringify(body));
  process.exit(4);
}
if (api.editDistance("cat", "car") !== 1) process.exit(5);
if (api.editDistance("cat", "dog") <= 2) process.exit(6);
const src = fs.readFileSync(process.argv[1], "utf8");
// Semantic search is parked (no embeddings): the mode may be listed only as a disabled option.
for (const line of src.split("\n")) {
  if (line.indexOf('value: "semantic"') >= 0 && line.indexOf("disabled: true") < 0) process.exit(7);
}
if (src.indexOf("limit: 250") < 0) process.exit(8);
"""
    proc = subprocess.run(
        [node, "-e", script, str(editor)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_save_blocks_on_a_warning_graded_error(tmp_path: Path, make_config) -> None:
    """C-049 / ADR-72: ``[validate.severity] V17 = "error"`` stops the editor save."""
    setup_project(tmp_path, {"greet": "Hello"}, existing={})
    cfg = make_config(tmp_path)
    app = build_state(cfg)
    assert save(app, "pl", "app", "greet", "Witaj ")["ok"] is True  # V17 is only a warning by default
    cfg.severity_overrides = {"V17": "error"}
    blocked = save(app, "pl", "app", "greet", "Witaj  ")
    assert blocked["ok"] is False
    assert blocked["errors"][0]["id"] == "V17"
    cfg.severity_overrides = {"V17": "off"}
    assert save(app, "pl", "app", "greet", "Witaj ")["ok"] is True
