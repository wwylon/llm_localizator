"""HTTP tests for ``POST /api/ops/*``."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.projects import load_config
from llm_localizator.web import build_state
from llm_localizator.web.server import _Handler

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
"""


@pytest.fixture
def ops_server(tmp_path: Path):
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {"greet": "Cześć"})
    cfg = load_config(tmp_path / ".llm-localize.toml")
    states = {"demo": build_state(cfg)}
    handler = type("Handler", (_Handler,), {
        "states": states,
        "default_project": "demo",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def _post(port: int, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_http_ops_validate(ops_server) -> None:
    status, payload = _post(ops_server, "/api/ops/validate", {})
    assert status == 200
    assert payload["command"] == "validate"
    assert "summary" in payload


def test_http_ops_status(ops_server) -> None:
    status, payload = _post(ops_server, "/api/ops/status", {})
    assert status == 200
    assert payload["command"] == "status"
    assert "locales" in payload["data"]


def test_http_ops_migrate_state_dry_run(ops_server) -> None:
    status, payload = _post(ops_server, "/api/ops/migrate-state", {"dry_run": True})
    assert status == 200
    assert payload["command"] == "migrate-state"


def test_http_ops_rescore_stream_first_byte(tmp_path: Path, monkeypatch) -> None:
    """Streaming must send headers + a log line before the run finishes."""
    import time

    monkeypatch.setattr("llm_localizator.ops.rescore.tq_available", lambda: False)
    (tmp_path / ".llm-localize.toml").write_text(
        CONFIG + '\n[provider]\nkind = "null"\n',
        encoding="utf-8",
    )
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {"greet": "Cześć"})
    cfg = load_config(tmp_path / ".llm-localize.toml")
    states = {"demo": build_state(cfg)}
    handler = type("Handler", (_Handler,), {
        "states": states,
        "default_project": "demo",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = json.dumps({"stream": True, "confirm": True, "locales": ["pl"]}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/ops/rescore",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert "text/event-stream" in (resp.headers.get("Content-Type") or "")
            assert time.time() - t0 < 2.0
            resp.fp.raw._sock.settimeout(3)
            chunk = resp.read(200)
            assert b"data: " in chunk
            assert (
                b"starting rescore" in chunk
                or b"collecting" in chunk
                or b"rescoring" in chunk
            )
    finally:
        server.shutdown()


def test_http_ops_unknown(ops_server) -> None:
    data = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{ops_server}/api/ops/not-a-command",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


def _get(port: int, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_report_parts_list_and_download_are_confined(ops_server, tmp_path):
    out = tmp_path / "reports" / "hardcoded"
    out.mkdir(parents=True)
    (out / "part-1.md").write_text("# part", encoding="utf-8")
    (out / "index.json").write_text(json.dumps({"parts": [{"file": "part-1.md"}]}), encoding="utf-8")
    # A folder inside the project is still listed when named; without ``dir`` the server looks in the engine data
    # home, where agent-hardcoded writes by default (ADR-112).
    code, body = _get(ops_server, "/api/report-parts?dir=reports%2Fhardcoded")
    assert code == 200 and json.loads(body)["parts"][0]["name"] == "part-1.md"
    code, body = _get(ops_server, "/api/report-part?name=part-1.md&dir=reports%2Fhardcoded")
    assert code == 200 and body == b"# part"
    assert _get(ops_server, "/api/report-part?name=..%2F..%2Fsecret.md")[0] == 404
    assert _get(ops_server, "/api/report-part?name=part-1.md&dir=..%2F..")[0] == 404
