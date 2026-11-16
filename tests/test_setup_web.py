"""Web endpoints behind the guided setup: language list, prefill, smoke test, guide op."""

from __future__ import annotations

from llm_localizator.projects.accounts import AccountStore
from llm_localizator.projects.config import load_config

from .test_w08 import _request, auth_server  # noqa: F401  (fixture re-export)


def _register_owner(port: int) -> None:
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })


def _translator_session(cfg) -> str:
    store = AccountStore(cfg.state_root())
    store.register("tr", "password1")
    tr = next(u for u in store.list_users() if u.username == "tr")
    store.set_role(tr.id, role="Translator", locales=["pl"])
    return store.create_session(store.find_by_id(tr.id))


def test_locales_endpoint_lists_selectable_languages(auth_server) -> None:
    port, _cfg = auth_server
    status, payload, _ = _request(port, "/api/locales")
    assert status == 200
    rows = {row["code"]: row for row in payload["locales"]}
    assert rows["pl"]["name"] == "Polish"
    assert rows["ar"]["direction"] == "rtl"
    assert "fr-CA" in rows and "pt-BR" in rows
    assert "pt" not in rows


def test_setup_state_prefills_the_wizard(auth_server) -> None:
    port, _cfg = auth_server
    status, payload, _ = _request(port, "/api/setup-state")
    assert status == 200
    assert payload["sourceLocale"] == "en"
    assert payload["targets"] == ["pl", "de"]
    assert payload["providerKind"] == "null"
    assert payload["catalogFormat"] == "json-nested"
    assert payload["model"]


def test_setup_saves_the_domain_and_refreshes_the_default_project(auth_server) -> None:
    port, cfg = auth_server
    _register_owner(port)
    # The wizard sends no project name on the account pages; that must still
    # refresh the default project's cached state, not a stray "" entry.
    status, payload, _ = _request(port, "/api/setup", method="POST", body={
        "project": "",
        "targets": ["pl", "fr-CA"],
        "domain": "a hotel booking app",
    })
    assert status == 200, payload
    reloaded = load_config(cfg.config_path)
    assert reloaded.targets == ["pl", "fr-CA"]
    assert reloaded.domain == "a hotel booking app"
    _status, state, _ = _request(port, "/api/setup-state")
    assert state["targets"] == ["pl", "fr-CA"]
    assert state["domain"] == "a hotel booking app"


def test_smoke_test_answers_for_an_admin(auth_server) -> None:
    port, _cfg = auth_server
    _register_owner(port)
    status, payload, _ = _request(port, "/api/setup/smoke-test", method="POST", body={
        "model": "my-model",
    })
    assert status == 200, payload
    assert payload["ok"] is True
    assert "my-model answered" in payload["message"]


def test_smoke_test_is_admin_only(auth_server) -> None:
    port, cfg = auth_server
    _register_owner(port)
    session = _translator_session(cfg)
    status, payload, _ = _request(
        port, "/api/setup/smoke-test", method="POST", session=session, body={},
    )
    assert status == 403


def test_smoke_test_needs_confirmation_for_a_paid_provider(auth_server) -> None:
    port, cfg = auth_server
    _register_owner(port)
    cfg.provider.kind = "anthropic"
    status, payload, _ = _request(port, "/api/setup/smoke-test", method="POST", body={})
    assert status == 400
    assert "paid provider" in payload["error"]


def test_guide_op_over_http_reports_the_next_step(auth_server) -> None:
    port, _cfg = auth_server
    status, payload, _ = _request(port, "/api/ops/guide", method="POST", body={
        "skip_provider": True,
    })
    assert status == 200
    data = payload["data"]
    assert data["hasConfig"] is True
    assert data["next"] in ("approach", "translate")  # approach first when none is recorded (ADR-123)
    assert [s["id"] for s in data["steps"]][:4] == ["environment", "project", "approach", "languages"]


def test_guide_op_never_runs_the_smoke_test_over_http(auth_server, tmp_path) -> None:
    port, cfg = auth_server
    _request(port, "/api/ops/guide", method="POST", body={"smoke_test": True, "skip_provider": True})
    assert not (cfg.state_root() / ".guide.json").exists()
