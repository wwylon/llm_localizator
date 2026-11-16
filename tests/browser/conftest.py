"""Playwright fixtures (ADR-27 amendment): real server, scratch projects, headless Chromium.

Run: ``uv run --extra e2e pytest tests/browser -m browser``. Everything skips
when Playwright or Chromium is unavailable; the default run deselects the
``browser`` marker.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.projects import load_config
from llm_localizator.web import build_state
from llm_localizator.web.server import _Handler

from ..conftest import write_json

TOKEN = "browser-test-token"

CONFIG = """
[project]
name = "{name}"

[catalog]
path = "messages/{{locale}}/{{namespace}}.json"

[locales]
targets = {targets}

[state]
dir = "messages/.state"
"""


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/browser" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.browser)


@pytest.fixture(scope="session")
def _browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    pw = sync_api.sync_playwright().start()
    try:
        browser = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001 - Chromium not installed
        pw.stop()
        pytest.skip(f"Chromium unavailable: {exc}")
    yield browser
    browser.close()
    pw.stop()


class _Server(ThreadingHTTPServer):
    # The default listen backlog of 5 refuses connections when a page fires a burst of fetches (Windows answers
    # with ERR_CONNECTION_REFUSED instead of queueing), which failed smoke tests at random.
    request_queue_size = 128
    daemon_threads = True


@dataclass
class Ui:
    base: str
    src: object
    dst: object
    page: object
    errors: list


def _project(root: Path, name: str, targets: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".llm-localize.toml").write_text(
        CONFIG.format(name=name, targets=targets), encoding="utf-8")
    write_json(root / "messages" / "en" / "app.json", {"greet": "Hello", "bye": "Bye"})
    for loc in ("pl", "ar"):
        write_json(root / "messages" / loc / "app.json", {"greet": "x", "bye": "y"})
    return load_config(root / ".llm-localize.toml")


@pytest.fixture
def ui(tmp_path: Path, _browser, monkeypatch):
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))  # no real registry
    src = _project(tmp_path / "src", "src", '["pl", "ar"]')
    dst = _project(tmp_path / "dst", "dst", '["pl"]')
    handler = type("Handler", (_Handler,), {
        "states": {"src": build_state(src), "dst": build_state(dst)},
        "default_project": "src",
        "session_token": TOKEN,
    })
    httpd = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    context = _browser.new_context()
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    yield Ui(f"http://127.0.0.1:{httpd.server_address[1]}", src, dst, page, errors)
    context.close()
    httpd.shutdown()
