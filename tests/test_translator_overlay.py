"""HTTP and unit tests for the translator overlay."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.projects import load_config
from llm_localizator.web import build_state
from llm_localizator.web.server import _Handler
from llm_localizator.web.translator import (
    WEB_UI_NS,
    save_web_ui_string,
    translator_bundle,
    translator_bundle_web_ui,
)

from .conftest import write_json

CONFIG = """
[project]
name = "demo"

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]

[state]
dir = "messages/.state"
flags = "messages/.flags.jsonl"
"""


@pytest.fixture
def app(tmp_path: Path):
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {
        "greet": "Hello",
        "bye": "Goodbye",
    })
    write_json(tmp_path / "messages" / "pl" / "app.json", {
        "greet": "Cześć",
        "bye": "Do widzenia",
    })
    return build_state(load_config(tmp_path / ".llm-localize.toml"))


@pytest.fixture
def web_server(app, tmp_path: Path):
    handler = type("Handler", (_Handler,), {
        "states": {"demo": app},
        "default_project": "demo",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def _get(port: int, path: str, *, origin: str = "") -> tuple[int, bytes, dict]:
    headers = {"Origin": origin} if origin else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read(), dict(resp.headers)


def _post(port: int, path: str, body: dict, *, origin: str = "") -> tuple[int, dict, dict]:
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)


def test_translator_bundle_web_ui() -> None:
    bundle = translator_bundle_web_ui("pl")
    assert bundle["mode"] == "web-ui"
    assert bundle["sourceLocale"] == "en"
    keys = {e["key"] for e in bundle["entries"]}
    assert "filterAll" in keys
    assert all(e["namespace"] == WEB_UI_NS for e in bundle["entries"])


def test_translator_bundle_project(app) -> None:
    bundle = translator_bundle(app, "pl")
    assert bundle["mode"] == "project"
    keys = {(e["namespace"], e["key"]) for e in bundle["entries"]}
    assert ("app", "greet") in keys
    assert bundle["byTargetText"]["Cześć"] == [{"namespace": "app", "key": "greet"}]


def test_save_web_ui_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_localizator.web import translator as tr

    locales = tmp_path / "locales"
    locales.mkdir()
    (locales / "en.json").write_text('{"filterAll": "all statuses"}', encoding="utf-8")
    monkeypatch.setattr(tr, "web_ui_locales_dir", lambda: locales)
    state = tmp_path / "state"

    ok = save_web_ui_string(
        "pl", "filterAll", "wszystkie statusy", state_root=state,
    )
    assert ok["ok"] is True
    override = state / "web_ui" / "pl.json"
    data = json.loads(override.read_text(encoding="utf-8"))
    assert data["filterAll"] == "wszystkie statusy"
    merged = tr._load_web_ui_target("pl", state_root=state)
    assert merged["filterAll"] == "wszystkie statusy"

    bad = save_web_ui_string("en", "filterAll", "x", state_root=state)
    assert bad["ok"] is False
    missing = save_web_ui_string("pl", "filterAll", "x")
    assert missing["ok"] is False


def test_http_overlay_assets(web_server) -> None:
    status, body, _ = _get(web_server, "/overlay.js")
    assert status == 200
    assert b"LlmTranslatorOverlay" in body

    status, body, _ = _get(web_server, "/overlay.css")
    assert status == 200
    assert b"llm-tip" in body


def test_http_translator_lookup(web_server) -> None:
    status, body, _ = _get(
        web_server,
        "/api/translator-lookup?locale=pl&namespace=app&key=greet&project=demo",
    )
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["source"] == "Hello"
    assert data["target"] == "Cześć"


def test_http_translator_bundle_cors(web_server) -> None:
    status, body, headers = _get(
        web_server,
        "/api/translator-bundle?mode=web-ui&locale=pl",
        origin="http://localhost:3000",
    )
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
    data = json.loads(body.decode("utf-8"))
    assert data["mode"] == "web-ui"

    status, body, _ = _get(
        web_server,
        "/api/translator-bundle?locale=pl&project=demo",
    )
    data = json.loads(body.decode("utf-8"))
    assert data["mode"] == "project"
    assert any(e["key"] == "greet" for e in data["entries"])


def test_http_save_ui_locale(web_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_localizator.web import translator as tr

    locales = tmp_path / "locales"
    locales.mkdir()
    (locales / "en.json").write_text('{"filterAll": "all statuses"}', encoding="utf-8")
    (locales / "pl.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tr, "web_ui_locales_dir", lambda: locales)

    status, payload, _ = _post(web_server, "/api/save-ui-locale", {
        "locale": "pl",
        "key": "filterAll",
        "value": "wszystkie",
    })
    assert status == 200
    assert payload["ok"] is True


def test_page_includes_translator_overlay() -> None:
    from pathlib import Path
    from llm_localizator.web.assets import WEB_FEATURES

    editor = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "editor.js").read_text(encoding="utf-8")
    assert "translator_overlay" in WEB_FEATURES
    # Overlay remains available via overlay.js; toolbar no longer ships Translator mode.
    assert "translator-mode-btn" not in editor
    assert "dataset.llmKey" in editor
    overlay = (
        Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "overlay" / "overlay.js"
    ).read_text(encoding="utf-8")
    assert "__LLM_TRANSLATOR__" in overlay or "LlmTranslatorOverlay" in overlay
    assert "/api/resolve" in overlay


def test_overlay_js_hit_detection() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "overlay" / "overlay.js").read_text(
        encoding="utf-8"
    )
    assert "data-i18n-key" in js
    assert "reverseIndex" in js
    assert "byTargetText" in js or "indexReverseFromBundle" in js
    assert "guardInteraction" in js
    assert "/api/resolve" in js
    assert "/api/translator-lookup" in js
    assert "lookupEntryAsync" in js


def test_overlay_css_ctrl_lock() -> None:
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "overlay" / "overlay.css").read_text(
        encoding="utf-8"
    )
    assert "user-select: none" in css
    assert "onMouseUp" not in css
    js = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "overlay" / "overlay.js").read_text(
        encoding="utf-8"
    )
    assert "onMouseUp" in js
    assert "elementsStackAt" in js


def test_resolve_text_exact(app) -> None:
    from llm_localizator.web.translator import resolve_text

    r = resolve_text(app, "pl", "Cześć")
    assert r["candidates"]
    assert r["candidates"][0]["namespace"] == "app"
    assert r["candidates"][0]["key"] == "greet"


def test_resolve_text_hint(app) -> None:
    from llm_localizator.web.translator import resolve_text

    r = resolve_text(app, "pl", "anything", hint_ns="app", hint_key="bye")
    assert len(r["candidates"]) == 1
    assert r["candidates"][0]["key"] == "bye"
    assert r["candidates"][0]["score"] == 100


def test_resolve_text_fuzzy(app) -> None:
    from llm_localizator.web.translator import resolve_text

    r = resolve_text(app, "pl", "Cze")
    keys = {c["key"] for c in r["candidates"]}
    assert "greet" in keys


def test_translator_bundle_duplicate_targets(tmp_path: Path) -> None:
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {
        "a": "Same",
        "b": "Same",
    })
    write_json(tmp_path / "messages" / "pl" / "app.json", {
        "a": "To samo",
        "b": "To samo",
    })
    st = build_state(load_config(tmp_path / ".llm-localize.toml"))
    bundle = translator_bundle(st, "pl")
    assert len(bundle["byTargetText"]["To samo"]) == 2
