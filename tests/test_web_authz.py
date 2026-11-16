"""Plan-review-7 phase 1: one POST policy table, locale scope, deny-by-default role."""

from __future__ import annotations

import base64
import inspect
import re
import urllib.error
import urllib.request

import pytest

from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.permissions import ROLE_ADMIN
from llm_localizator.projects.accounts import AccountStore
from llm_localizator.web.post_policy import POST_POLICY
from llm_localizator.web.server import _Handler

from .test_w08 import _request, auth_server  # noqa: F401  (fixture re-export)


def _session(cfg, name: str, role: str, locales: list[str]) -> str:
    store = AccountStore(cfg.state_root())
    store.register(name, "password1")
    user = next(u for u in store.list_users() if u.username == name)
    store.set_role(user.id, role=role, locales=locales)
    return store.create_session(store.find_by_id(user.id))


def _owner(port: int) -> None:
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })


# --- policy table ---------------------------------------------------------


def test_every_post_route_is_in_the_policy_table() -> None:
    missing = [p for p in _Handler._POST_ROUTES if p not in POST_POLICY]
    assert not missing, f"POST routes missing from POST_POLICY: {missing}"
    src = inspect.getsource(_Handler.do_POST)
    inline = set(re.findall(r'url\.path == "(/api/[^"]+)"', src))
    assert not [p for p in inline if p not in POST_POLICY], inline
    assert set(POST_POLICY.values()) <= {"admin", "edit", "read", "inline"}


def test_dispatch_op_denies_missing_role(tmp_path, make_config) -> None:
    from .conftest import setup_project

    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    cfg = make_config(tmp_path)
    denied = dispatch_op(cfg, "status", {"locales": ["pl"]})
    assert denied["ok"] is False and denied["exit_code"] == 77
    ok = dispatch_op(cfg, "status", {"locales": ["pl"]}, actor_role=ROLE_ADMIN)
    assert ok.get("ok") is not False


# --- translator scoped to pl ----------------------------------------------

_EDIT_BODIES = {
    "/api/save": {"locale": "de", "namespace": "app", "key": "greet", "value": "x"},
    "/api/flag": {"locale": "de", "namespace": "app", "key": "greet"},
    "/api/verify": {"locale": "de", "namespace": "app", "key": "greet"},
    "/api/revert": {"locale": "de", "namespace": "app", "key": "greet", "value": "x"},
    "/api/validate-key": {"locale": "de", "namespace": "app", "key": "greet", "value": "x"},
    "/api/mark-example": {"locale": "de", "namespace": "app", "key": "greet"},
    "/api/mark-intentional": {"locale": "de", "namespace": "app", "key": "greet"},
    "/api/lock": {"locale": "de", "namespace": "app", "key": "greet", "locked": True},
    "/api/retranslate": {"locales": ["pl", "de"]},
    "/api/tm/import": {"locale": "de", "tmx": "<tmx/>"},
    "/api/import": {"locales": ["pl", "de"], "csv": "a"},
    "/api/export": {"locales": ["pl", "de"]},
    "/api/resolve": {"locale": "de", "text": "Hallo"},
    "/api/save-ui-locale": {"locale": "de", "key": "k", "value": "v"},
    "/api/review/tickets": {"locale": "de", "namespace": "app", "key": "greet", "reason": "r"},
    "/api/ops/validate": {"locales": ["pl", "de"]},
}
_ADMIN_ONLY = [
    "/api/settings", "/api/project-config", "/api/web-token", "/api/add-locale",
    "/api/remove-locale", "/api/translate-enabled", "/api/reload", "/api/setup",
    "/api/model-eval/run", "/api/model-eval/apply", "/api/setup/smoke-test",
]


@pytest.mark.parametrize("path", sorted(_EDIT_BODIES))
def test_translator_pl_cannot_touch_de_on_post(auth_server, path) -> None:
    port, cfg = auth_server
    _owner(port)
    sess = _session(cfg, "tr", "Translator", ["pl"])
    status, payload, _ = _request(
        port, path, method="POST", body=_EDIT_BODIES[path], session=sess,
    )
    assert status == 403, (path, payload)


@pytest.mark.parametrize("path", _ADMIN_ONLY)
def test_translator_with_token_is_refused_on_admin_routes(auth_server, path) -> None:
    port, cfg = auth_server
    _owner(port)
    sess = _session(cfg, "tr", "Translator", ["pl"])
    status, payload, _ = _request(
        port, path, method="POST", body={"locale": "pl"}, session=sess,
    )
    assert status == 403, (path, payload)


@pytest.mark.parametrize("path", [
    "/api/export?locales=de",
    "/api/export?locales=pl,de",
    "/api/bundle?locale=de",
    "/api/tm/concordance?locale=de&query=a",
    "/api/tm/browse?locale=de",
    "/api/tm/export?locale=de",
    "/api/analysis?locale=de",
    "/api/review/tickets?locale=de",
    "/api/translator-bundle?locale=de",
])
def test_translator_pl_cannot_read_de(auth_server, path) -> None:
    port, cfg = auth_server
    _owner(port)
    sess = _session(cfg, "tr", "Translator", ["pl"])
    status, payload, _ = _request(port, path, session=sess)
    assert status == 403, (path, payload)


def test_export_default_locales_are_limited_to_allowed(auth_server) -> None:
    port, cfg = auth_server
    _owner(port)
    sess = _session(cfg, "tr", "Translator", ["pl"])
    status, payload, _ = _request(
        port, "/api/export", method="POST", body={"format": "csv"}, session=sess,
    )
    assert status == 200, payload
    text = base64.b64decode(payload["file_base64"]).decode("utf-8")
    assert "Hallo" not in text


def test_projects_list_is_filtered(auth_server, monkeypatch) -> None:
    port, cfg = auth_server
    _owner(port)
    sess = _session(cfg, "tr", "Translator", ["pl"])
    monkeypatch.setattr(
        "llm_localizator.web.server.load_registry", lambda: {"other": object()},
    )
    status, payload, _ = _request(port, "/api/projects", session=sess)
    assert status == 200
    assert [p["name"] for p in payload["projects"]] == ["demo"]


def test_review_comment_author_comes_from_session(auth_server) -> None:
    port, cfg = auth_server
    _owner(port)
    sess = _session(cfg, "tr", "Translator", ["pl"])
    status, created, _ = _request(
        port, "/api/review/tickets", method="POST", session=sess,
        body={"locale": "pl", "namespace": "app", "key": "greet", "reason": "r"},
    )
    assert status == 200, created
    tid = created.get("id") or (created.get("ticket") or {}).get("id")
    status, out, _ = _request(
        port, f"/api/review/tickets/{tid}/comment", method="POST", session=sess,
        body={"locale": "pl", "body": "hi", "author": "someone-else"},
    )
    assert status == 200, out
    status, listed, _ = _request(port, "/api/review/tickets?locale=pl", session=sess)
    text = str(listed)
    assert "someone-else" not in text and "tr" in text


# --- origin ---------------------------------------------------------------


def _raw_post(port, path, headers, body=b"{}"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body, method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_cross_origin_post_is_refused(auth_server) -> None:
    port, _cfg = auth_server
    assert _raw_post(
        port, "/api/reload",
        {"X-LLM-Token": "secret-token", "Origin": "http://evil.example"},
    ) == 403


def test_localhost_other_port_post_needs_overlay_edit(auth_server) -> None:
    port, cfg = auth_server
    assert cfg.overlay_edit is False
    assert _raw_post(
        port, "/api/save",
        {"X-LLM-Token": "secret-token", "Origin": "http://localhost:1234"},
        body=b'{"locale":"pl","namespace":"app","key":"greet","value":"x"}',
    ) == 403


def test_invalid_scope_is_400_not_500(auth_server) -> None:
    port, _cfg = auth_server
    for body in (
        {"locale": "../x", "namespace": "app", "key": "greet", "value": "x"},
        {"locale": "pl", "namespace": "", "key": "greet", "value": "x"},
        {"locale": "pl", "namespace": "nope", "key": "greet", "value": "x"},
    ):
        status, payload, _ = _request(port, "/api/save", method="POST", body=body)
        assert status == 400, (body, payload)


def test_analysis_report_filters_to_allowed_locales(auth_server) -> None:
    port, cfg = auth_server
    _owner(port)
    sess = _session(cfg, "tr", "Translator", ["pl"])
    status, payload, _ = _request(port, "/api/analysis/report", session=sess)
    assert status == 200, payload
    assert payload["ok"] is True
    assert {r["locale"] for r in payload["locales"]} <= {"pl"}


@pytest.mark.parametrize("path", [
    "/api/overview-stats",
    "/api/overview-lite",
    "/api/progress",
    "/api/usage",
    "/api/status",
])
def test_aggregate_gets_filter_to_allowed_locales(auth_server, path) -> None:
    port, cfg = auth_server
    _owner(port)
    sess = _session(cfg, "tr2", "Translator", ["pl"])
    status, payload, _ = _request(port, path, session=sess)
    assert status == 200, (path, payload)
    if path == "/api/overview-lite":
        assert set(payload.get("activeLocales") or []) <= {"pl"}
        assert set(payload.get("frozenLocales") or []) <= {"pl"}
        return
    rows = payload.get("locales") or (payload.get("data") or {}).get("locales") or []
    assert {r["locale"] for r in rows if isinstance(r, dict)} <= {"pl"}, (path, payload)


def test_project_with_missing_config_gets_409_and_a_hint(auth_server, tmp_path, monkeypatch) -> None:
    from llm_localizator.projects.registry import register_project

    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))
    register_project("ghost", tmp_path / "ghost")
    port, _cfg = auth_server
    _owner(port)
    status, payload, _ = _request(port, "/api/analysis/report?project=ghost")
    assert status == 409, payload
    assert payload["ok"] is False
    assert "no config file" in payload["error"]
    assert "llm-localizator init" in payload["hint"]
