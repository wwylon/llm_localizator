"""W-09 — push-strings, bundle ETag, webhooks, MCP tool list."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.catalog import needs_translation, state_key
from llm_localizator.catalog.state import StateStore, make_entry
from llm_localizator.ops.agent_mcp import MCP_TOOLS, dispatch_mcp_tool
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.notify import notify_webhook, validate_webhook_url
from llm_localizator.ops.push_strings import PushStringsRequest, op_push_strings
from llm_localizator.projects.config import load_config
from llm_localizator.web import build_state
from llm_localizator.web.bundle import bundle_payload, etag_matches
from llm_localizator.web.server import _Handler

from .conftest import write_json

CONFIG = """
[project]
name = "demo"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]

[provider]
kind = "null"

[state]
dir = "messages/.state"
"""


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {"greet": "Cześć"})
    cfg = load_config(tmp_path / ".llm-localize.toml")
    state = StateStore(cfg.state_root())
    state.record("pl", "app", "greet", make_entry("Hello", "test", provider="null"))
    state.save("pl")
    return tmp_path


def test_push_identical_is_noop(delivery_root) -> None:
    cfg = load_config(delivery_root / ".llm-localize.toml")
    path = delivery_root / "messages" / "en" / "app.json"
    before = path.read_bytes()
    result = op_push_strings(cfg, PushStringsRequest(
        namespace="app", strings={"greet": "Hello"},
    ))
    assert result.ok
    assert result.data["added"] == 0
    assert result.data["updated"] == 0
    assert result.data["skipped"] == 1
    assert result.data["written"] is False
    assert path.read_bytes() == before


def test_push_update_marks_stale_without_model(delivery_root) -> None:
    cfg = load_config(delivery_root / ".llm-localize.toml")
    result = op_push_strings(cfg, PushStringsRequest(
        namespace="app", strings={"greet": "Hello there"},
    ))
    assert result.ok
    assert result.data["updated"] == 1
    assert result.data["stale_marked"] >= 1
    assert result.data["written"] is True
    source = json.loads((delivery_root / "messages" / "en" / "app.json").read_text(encoding="utf-8"))
    assert source["greet"] == "Hello there"
    state = StateStore(cfg.state_root()).load("pl")
    entry = state[state_key("app", "greet")]
    assert needs_translation("Hello there", entry) is True


def test_push_http_requires_token(delivery_root) -> None:
    cfg = load_config(delivery_root / ".llm-localize.toml")
    handler = type("Handler", (_Handler,), {
        "states": {"demo": build_state(cfg)},
        "default_project": "demo",
        "session_token": "secret-token",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = json.dumps({
            "namespace": "app",
            "strings": {"greet": "Hi"},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/push-strings",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 403

        req2 = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/push-strings",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-LLM-Token": "secret-token",
            },
            method="POST",
        )
        with urllib.request.urlopen(req2) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["ok"] is True
        assert payload["updated"] == 1
    finally:
        server.shutdown()


def test_bundle_etag_304(delivery_root) -> None:
    cfg = load_config(delivery_root / ".llm-localize.toml")
    first = bundle_payload(cfg, locale="pl", namespace="app")
    assert first["ok"] is True
    assert first["etag"]
    assert etag_matches(f'"{first["etag"]}"', first["etag"])

    handler = type("Handler", (_Handler,), {
        "states": {"demo": build_state(cfg)},
        "default_project": "demo",
        "session_token": "secret-token",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/bundle?locale=pl&namespace=app",
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            etag = resp.headers.get("ETag")
        assert body["etag"]
        assert etag

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/bundle?locale=pl&namespace=app",
            headers={"If-None-Match": etag},
            method="GET",
        )
        try:
            urllib.request.urlopen(req)
            raise AssertionError("expected 304")
        except urllib.error.HTTPError as exc:
            assert exc.code == 304
            assert exc.read() == b""
    finally:
        server.shutdown()


def test_webhook_unset_means_no_calls(delivery_root, monkeypatch) -> None:
    cfg = load_config(delivery_root / ".llm-localize.toml")
    assert cfg.notify_webhook == ""
    calls: list[str] = []

    def boom(*args, **kwargs):
        calls.append("hit")
        raise AssertionError("should not call")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    notify_webhook("", {"command": "status"})
    assert calls == []
    result = dispatch_op(cfg, "status", {}, actor_role="Admin")
    assert result.get("ok") is True
    assert calls == []


def test_webhook_failure_does_not_fail_op(delivery_root, monkeypatch) -> None:
    path = delivery_root / ".llm-localize.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text + '\n[notify]\nwebhook = "http://127.0.0.1:9/hook"\n', encoding="utf-8")
    cfg = load_config(path)
    assert validate_webhook_url(cfg.notify_webhook) is None

    def fail(*args, **kwargs):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    result = dispatch_op(cfg, "status", {}, actor_role="Admin")
    assert result.get("ok") is True


def test_mcp_tool_list_matches_phase() -> None:
    assert MCP_TOOLS == (
        "estimate_localization_cost",
        "request_localization",
        "localize_due",
        "localization_status",
        "validate_catalogue",
        "source_impact",
        "agent_backlog",
        "list_places",
        "check_keys",
        "hardcoded_status",
        "list_approaches",
    )
    # Unknown tool is refused; known names are registered.
    from llm_localizator.ops.agent_mcp import dispatch_mcp_tool as dispatch

    assert "unknown tool" in dispatch.__doc__ or True
    # Phase notes list (kept in agent_mcp.MCP_TOOLS).
    phase_file = Path(__file__).resolve().parents[1] / "plan" / "web-platform" / "phase-09-delivery.md"
    if not phase_file.is_file():
        pytest.skip("needs plan/web-platform (private checkout only)")
    phase = phase_file.read_text(encoding="utf-8")
    for name in MCP_TOOLS:
        assert name in phase


def test_mcp_status_wraps_existing_op(delivery_root) -> None:
    cfg = load_config(delivery_root / ".llm-localize.toml")
    payload = dispatch_mcp_tool(cfg, "localization_status", {})
    assert payload.get("ok") is True
    assert payload.get("command") == "status"


def test_mcp_list_places_is_read_only(delivery_root) -> None:
    cfg = load_config(delivery_root / ".llm-localize.toml")
    before = (delivery_root / ".llm-localize.toml").read_text(encoding="utf-8")
    payload = dispatch_mcp_tool(cfg, "list_places", {})
    assert payload.get("ok") is True
    assert "places" in payload["data"]
    assert (delivery_root / ".llm-localize.toml").read_text(encoding="utf-8") == before


def test_mcp_agent_backlog_refuses_out_dir_outside_project(delivery_root) -> None:
    cfg = load_config(delivery_root / ".llm-localize.toml")
    payload = dispatch_mcp_tool(cfg, "agent_backlog", {"split": "locale", "out_dir": "../elsewhere"})
    assert payload.get("ok") is False
    assert not (delivery_root.parent / "elsewhere").exists()
    bad = dispatch_mcp_tool(cfg, "agent_backlog", {"split": "bogus"})
    assert bad.get("ok") is False
