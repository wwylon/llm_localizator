"""ADR-46 — session edited_by stamps and translator activity ledger."""

from __future__ import annotations

import json
import threading
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import urllib.error
import urllib.request

from llm_localizator.catalog.history import HistoryStore
from llm_localizator.catalog.translator_activity import ACTIVITY_NAME, summarize_activity
from llm_localizator.projects.accounts import AccountStore
from llm_localizator.projects.config import load_config
from llm_localizator.web import build_state
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
targets = ["pl", "de"]

[provider]
kind = "null"

[state]
dir = "messages/.state"
"""


@pytest.fixture
def activity_server(tmp_path: Path):
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {"greet": "Cześć"})
    write_json(tmp_path / "messages" / "de" / "app.json", {"greet": "Hallo"})
    cfg = load_config(tmp_path / ".llm-localize.toml")
    states = {"demo": build_state(cfg)}
    handler = type("Handler", (_Handler,), {
        "states": states,
        "default_project": "demo",
        "session_token": "secret-token",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port, cfg, states
    server.shutdown()


def _request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = "secret-token",
    session: str | None = None,
) -> tuple[int, dict]:
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-LLM-Token"] = token
    if session:
        headers["X-LLM-Session"] = session
    if body is not None or method == "POST":
        data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with opener.open(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload


def test_session_save_stamps_edited_by(activity_server) -> None:
    port, cfg, _states = activity_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    store.register("tr", "password1")
    tr = next(u for u in store.list_users() if u.username == "tr")
    store.set_role(tr.id, role="Translator", locales=["pl"])
    session = store.create_session(store.find_by_id(tr.id))

    status, payload = _request(
        port, "/api/save", method="POST",
        token="secret-token",
        session=session,
        body={
            "locale": "pl", "namespace": "app", "key": "greet",
            "value": "Witaj",
        },
    )
    assert status == 200, payload
    assert payload.get("ok") is True

    events = HistoryStore(cfg.history_root()).events_for("pl", "app", "greet")
    assert events
    latest = events[-1]
    assert latest.trigger == "web-edit"
    assert latest.edited_by == tr.id
    assert latest.edited_by_name == "tr"

    ledger = cfg.state_root() / ACTIVITY_NAME
    assert ledger.exists()
    lines = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(row["user_id"] == tr.id and row["trigger"] == "web-edit" for row in lines)


def test_token_save_leaves_edited_by_unset(activity_server) -> None:
    port, cfg, _states = activity_server
    status, payload = _request(
        port, "/api/save", method="POST",
        body={
            "locale": "pl", "namespace": "app", "key": "greet",
            "value": "Siema",
        },
    )
    assert status == 200, payload
    events = HistoryStore(cfg.history_root()).events_for("pl", "app", "greet")
    assert events
    assert events[-1].edited_by is None
    assert not (cfg.state_root() / ACTIVITY_NAME).exists()


def test_translator_activity_aggregates(activity_server) -> None:
    port, cfg, _states = activity_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    owner = store.list_users()[0]
    store.register("tr", "password1")
    tr = next(u for u in store.list_users() if u.username == "tr")
    store.set_role(tr.id, role="Translator", locales=["pl"])
    session = store.create_session(store.find_by_id(tr.id))

    _request(
        port, "/api/save", method="POST",
        token="secret-token", session=session,
        body={"locale": "pl", "namespace": "app", "key": "greet", "value": "Hej"},
    )
    _request(
        port, "/api/verify", method="POST",
        token="secret-token", session=session,
        body={"locale": "pl", "namespace": "app", "key": "greet", "verify": True},
    )

    admin_session = store.create_session(owner)
    status, payload = _request(
        port, "/api/translator-activity?project=demo",
        method="GET",
        token="secret-token",
        session=admin_session,
    )
    assert status == 200, payload
    assert payload["ok"] is True
    by_name = {row["username"]: row for row in payload["translators"]}
    assert "tr" in by_name
    assert by_name["tr"]["total"] >= 2
    assert by_name["tr"]["byTrigger"].get("web-edit", 0) >= 1
    assert by_name["tr"]["byTrigger"].get("web-verify", 0) >= 1
    assert any(ev["trigger"] == "web-edit" for ev in payload["timeline"])


def test_translator_activity_denied_for_translator(activity_server) -> None:
    port, cfg, _states = activity_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    store.register("tr", "password1")
    tr = next(u for u in store.list_users() if u.username == "tr")
    store.set_role(tr.id, role="Translator", locales=["pl"])
    session = store.create_session(store.find_by_id(tr.id))

    status, payload = _request(
        port, "/api/translator-activity?project=demo",
        method="GET",
        token="secret-token",
        session=session,
    )
    assert status == 403
    assert "Supervisor" in payload["error"] or "Admin" in payload["error"]


def test_summarize_activity_unit(tmp_path: Path) -> None:
    from llm_localizator.catalog.translator_activity import append_activity

    root = tmp_path / "state"
    append_activity(
        root, user_id="u1", username="alice",
        locale="pl", namespace="app", key="a", trigger="web-edit",
    )
    append_activity(
        root, user_id="u1", username="alice",
        locale="pl", namespace="app", key="b", trigger="web-verify",
    )
    append_activity(
        root, user_id="u2", username="bob",
        locale="de", namespace="app", key="a", trigger="web-edit",
    )
    summary = summarize_activity(root, limit=10)
    assert summary["total"] == 3
    assert len(summary["translators"]) == 2
    alice = next(r for r in summary["translators"] if r["user_id"] == "u1")
    assert alice["byTrigger"] == {"web-edit": 1, "web-verify": 1}
