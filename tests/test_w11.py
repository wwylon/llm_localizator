"""W-11 — marketing pages, UI locale, CAT shortcuts, edit distance."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from llm_localizator.catalog import KNOWN_FORMATS, ScoreStore
from llm_localizator.web.api_routes import API_EXACT_PATHS, API_PATHS, API_ROUTES
from llm_localizator.web.marketing import (
    format_ids,
    install_command,
    phase_statuses,
    render_api_docs,
    render_landing,
    render_roadmap,
)
from llm_localizator.web.shell import render_shell

from .conftest import setup_project

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "llm_localizator" / "web" / "static"
LOCALES = ROOT / "llm_localizator" / "web" / "locales"
SERVER = ROOT / "llm_localizator" / "web" / "server.py"


def test_landing_formats_match_registry() -> None:
    html = render_landing(app_port=8770)
    shown = re.findall(r'data-format="([^"]+)"', html)
    assert shown
    assert set(shown) <= set(KNOWN_FORMATS)
    assert set(shown) == set(format_ids())
    assert "411" not in html
    assert "feature-card card" in html
    assert "Hardcoded-string finder" in html
    assert "Review panel" in html
    assert 'href="#features"' in html
    assert 'href="#how"' in html
    assert 'href="#formats"' in html
    assert 'href="#install"' in html
    assert 'id="features"' in html
    assert 'id="how"' in html
    assert 'id="formats"' in html
    assert 'id="install"' in html
    assert 'href="http://127.0.0.1:8770/app"' in html
    assert 'aria-label="On this page"' in html
    cmd = install_command()
    assert cmd
    assert cmd in html
    # No invented demo catalogue counts; no local-only claim now that cloud engines exist.
    assert "1518" not in html
    assert "0.0.0.0" not in html
    assert "cloud dependencies" not in html
    assert "mkt-stats" in html


def test_how_it_works_is_filled() -> None:
    from llm_localizator.web.marketing import render_how_it_works

    html = render_how_it_works()
    assert 'data-page="how-it-works"' in html
    assert "agent-hardcoded" in html
    assert "W-11 fills this page." not in html


def test_roadmap_marks_todo_as_not_done() -> None:
    rows = phase_statuses()
    by_id = {row["id"]: row for row in rows}
    # Internal phases still parse; the page shows the public roadmap.json.
    assert by_id["W-01"]["done"] == "yes"
    html = render_roadmap()
    assert 'data-phase="W-01"' not in html
    assert 'data-status="done" data-done="yes"' in html
    assert 'data-status="planned" data-done="no"' in html


def test_api_docs_list_documented_paths() -> None:
    html = render_api_docs()
    for _method, path, _purpose in API_ROUTES:
        assert f'data-api-path="{path}"' in html
    assert "X-LLM-Token" in html
    assert "127.0.0.1" in html


def test_api_routes_do_not_drift_from_server() -> None:
    source = SERVER.read_text(encoding="utf-8")
    # Exact path comparisons in the handler.
    handled = set(re.findall(r'url\.path\s*==\s*["\'](/api/[^"\']+)["\']', source))
    # Route table dict keys (e.g. "/api/foo": "_handler").
    handled.update(re.findall(r'["\'](/api/[^"\']+)["\']\s*:\s*["\']_(?:get|post)_', source))
    # Prefix starts-with for ops.
    if 'url.path.startswith("/api/ops/")' in source:
        handled.add("/api/ops/{command}")
    if "review/tickets/" in source and "comment" in source:
        handled.add("/api/review/tickets/{id}/comment")
        handled.add("/api/review/tickets/{id}/status")
    missing_from_table = handled - API_PATHS
    assert not missing_from_table, f"server handles paths not in API_ROUTES: {sorted(missing_from_table)}"
    # Exact documented paths must appear in the server source.
    missing_from_server = API_EXACT_PATHS - handled
    assert not missing_from_server, (
        f"API_ROUTES exact paths missing from server: {sorted(missing_from_server)}"
    )


def test_ui_locale_dictionaries_and_fr() -> None:
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    fr = json.loads((LOCALES / "fr.json").read_text(encoding="utf-8"))
    assert "nav_dashboard" in en
    assert "nav_dashboard" in fr
    for code in ("en", "de", "pl", "fr", "ar"):
        path = LOCALES / f"{code}.json"
        assert path.is_file()
        orphans = set(json.loads(path.read_text(encoding="utf-8"))) - set(en)
        assert not orphans, f"{code}.json has keys en.json no longer has: {sorted(orphans)[:5]}"


def test_ui_locale_fr_is_complete() -> None:
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    fr = json.loads((LOCALES / "fr.json").read_text(encoding="utf-8"))
    assert set(en) == set(fr)


def test_ui_locale_js_rtl_and_storage() -> None:
    src = (STATIC / "ui-locale.js").read_text(encoding="utf-8")
    assert "llm_ui_locale" in src
    assert 'dir = isRtl ? "rtl" : "ltr"' in src
    assert "data-i18n" in src
    assert "en-XX" in src
    assert "XX marker (QA)" in src
    assert "__LLM_UI_QA_LOCALES" in src
    assert "ensureLang" in src
    assert "isAllowedLocale" in src
    html = render_shell("dashboard")
    assert 'id="lang-sel-mount"' in html
    assert "/static/ui-locale.js" in html
    assert 'data-i18n="nav_dashboard"' in html
    assert "window.__LLM_UI_QA_LOCALES=[]" in html
    html_qa = render_shell("dashboard", qa_locales=["en-XX"])
    assert 'window.__LLM_UI_QA_LOCALES=["en-XX"]' in html_qa


def test_ui_locale_path_en_xx_beats_stored_pl() -> None:
    """``/en-XX/…`` must not fall back to localStorage pl when QA inject is absent."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    script = r"""
const fs = require("fs");
const path = require("path");
const localesDir = process.argv[1];
const jsPath = process.argv[2];
const store = { llm_ui_locale: "pl" };
global.localStorage = {
  getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
  setItem(k, v) { store[k] = String(v); },
};
global.location = { pathname: "/en-XX/app/admin/activity", search: "", hash: "" };
global.document = {
  documentElement: { lang: "en", dir: "ltr" },
  cookie: "",
  querySelectorAll() { return []; },
  getElementById() { return null; },
};
global.fetch = function (url) {
  const m = String(url).match(/\/locales\/([^/]+)\.json/);
  const code = m ? decodeURIComponent(m[1]) : "en";
  const file = path.join(localesDir, code + ".json");
  if (!fs.existsSync(file)) {
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }
  const body = fs.readFileSync(file, "utf8");
  return Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(body)) });
};
global.window = global;
global.__LLM_UI_LOCALE = "en-XX";
// Intentionally omit __LLM_UI_QA_LOCALES — stale server used to drop the marker.
eval(fs.readFileSync(jsPath, "utf8"));
if (global.uiLocale.current !== "en-XX") {
  console.error("expected en-XX, got", global.uiLocale.current);
  process.exit(2);
}
if (store.llm_ui_locale !== "en-XX") process.exit(3);
process.exit(0);
"""
    proc = subprocess.run(
        [node, "-e", script, str(LOCALES), str(STATIC / "ui-locale.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_ui_locale_apply_rtl_with_node() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    script = r"""
const fs = require("fs");
const path = require("path");
const localesDir = process.argv[1];
const jsPath = process.argv[2];
const store = {};
global.localStorage = {
  getItem(k) { return store[k] || null; },
  setItem(k, v) { store[k] = String(v); },
};
global.document = {
  documentElement: { lang: "en", dir: "ltr" },
  querySelectorAll(sel) {
    if (sel === "[data-i18n]") return [{
      tagName: "SPAN", getAttribute() { return "nav_dashboard"; },
      set textContent(v) { this._t = v; }, get textContent() { return this._t; },
    }];
    if (sel === ".ui-locale-select") return [];
    return [];
  },
  getElementById() { return null; },
};
global.fetch = function (url) {
  const m = String(url).match(/\/locales\/([a-z]+)\.json/);
  const code = m ? m[1] : "en";
  const body = fs.readFileSync(path.join(localesDir, code + ".json"), "utf8");
  return Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(body)) });
};
global.window = global;
eval(fs.readFileSync(jsPath, "utf8"));
const api = global.uiLocale;
api.set("ar").then(function () {
  if (global.document.documentElement.dir !== "rtl") process.exit(2);
  if (global.document.documentElement.lang !== "ar") process.exit(3);
  if (store.llm_ui_locale !== "ar") process.exit(4);
  return api.set("en");
}).then(function () {
  if (global.document.documentElement.dir !== "ltr") process.exit(5);
  process.exit(0);
}).catch(function (err) {
  console.error(err);
  process.exit(1);
});
"""
    proc = subprocess.run(
        [node, "-e", script, str(LOCALES), str(STATIC / "ui-locale.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_editor_dir_auto_and_shortcuts() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    editor = STATIC / "editor.js"
    src = editor.read_text(encoding="utf-8")
    assert 'dir = "auto"' in src or 'dir="auto"' in src or "area.dir = \"auto\"" in src
    script = r"""
const fs = require("fs");
global.window = global;
global.document = undefined;
eval(fs.readFileSync(process.argv[1], "utf8"));
const api = global.llmEditor;
if (!api || !api.shortcutAction) process.exit(2);
// Enter in search must not save.
const enterSearch = api.shortcutAction(
  { key: "Enter", ctrlKey: false },
  { targetTag: "INPUT", targetId: "editor-search", targetType: "search" }
);
if (enterSearch !== null) process.exit(3);
// Ctrl+Enter in translation saves.
const save = api.shortcutAction(
  { key: "Enter", ctrlKey: true },
  { targetTag: "TEXTAREA", targetId: "translation-field" }
);
if (save !== "save") process.exit(4);
// Shortcuts blocked while help is open (except help toggle).
const blocked = api.shortcutAction(
  { key: "Enter", ctrlKey: true },
  { helpOpen: true, targetTag: "TEXTAREA", targetId: "translation-field" }
);
if (blocked !== null) process.exit(5);
if (api.fullEditDistance("abc", "abc") !== 0) process.exit(6);
if (api.fullEditDistance("kitten", "sitting") !== 3) process.exit(7);
process.exit(0);
"""
    proc = subprocess.run(
        [node, "-e", script, str(editor)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_edit_distance_does_not_write_scores(tmp_path, make_config) -> None:

    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    cfg = make_config(tmp_path)
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "greet", score=0.9, signals=[], text="Witaj")
    scores.save("pl")
    path = cfg.scores_root() / "pl.json"
    before = path.read_bytes()
    # Local Levenshtein only — no score write from computing distance.
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    editor = STATIC / "editor.js"
    script = r"""
const fs = require("fs");
global.window = global;
global.document = undefined;
eval(fs.readFileSync(process.argv[1], "utf8"));
const d = global.llmEditor.fullEditDistance("Witaj", "Witaj");
if (d !== 0) process.exit(2);
"""
    proc = subprocess.run(
        [node, "-e", script, str(editor)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert path.read_bytes() == before
    src = editor.read_text(encoding="utf-8")
    # History paint must not POST a score.
    hist = src[src.index("function paintHistory") : src.index("function paintDiff")]
    assert "/api/save" not in hist
    assert "scores" not in hist.lower() or "edit-distance" in hist


def test_marketing_server_is_read_only() -> None:
    """Marketing port serves HTML/static only — no catalogue APIs (ADR-45)."""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from llm_localizator.web.server import DEFAULT_PORT, _MarketingHandler

    handler = type("MarketingHandler", (_MarketingHandler,), {
        "app_port": DEFAULT_PORT,
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            html = resp.read().decode("utf-8")
        assert 'data-page="landing"' in html
        assert f"http://127.0.0.1:{DEFAULT_PORT}/app" in html
        assert "411" not in html

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/static/app.css") as resp:
            assert b"--color-accent" in resp.read()

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/save",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
            raise AssertionError("POST should fail")
        except urllib.error.HTTPError as exc:
            assert exc.code == 405
            body = json.loads(exc.read().decode("utf-8"))
            assert "read-only" in body.get("error", "")
    finally:
        server.shutdown()
        server.server_close()


def test_app_redirects_marketing_paths(tmp_path, make_config) -> None:
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from llm_localizator.web import build_state
    from llm_localizator.web.server import _Handler

    (tmp_path / "messages" / "en").mkdir(parents=True)
    (tmp_path / "messages" / "en" / "app.json").write_text(
        json.dumps({"greet": "Hello"}), encoding="utf-8",
    )
    cfg = make_config(tmp_path)
    handler = type("Handler", (_Handler,), {
        "states": {cfg.name: build_state(cfg)},
        "default_project": cfg.name,
        "session_token": "tok",
        "marketing_port": 8760,
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        try:
            opener.open(f"http://127.0.0.1:{port}/landing")
            raise AssertionError("expected redirect")
        except urllib.error.HTTPError as exc:
            assert exc.code == 302
            assert exc.headers.get("Location") == "http://127.0.0.1:8760/"
    finally:
        server.shutdown()
        server.server_close()
