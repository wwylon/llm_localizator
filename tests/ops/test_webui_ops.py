"""plan-webui ops: suggest, source review, bulk-clear, status by screen (ADR-53)."""

from __future__ import annotations

import json

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.catalog.review_queue import open_review_queue
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.permissions import ROLE_DEVELOPER, ROLE_TRANSLATOR, role_allowed
from llm_localizator.ops.status import screen_coverage
from llm_localizator.providers.null import NullProvider

from tests.conftest import setup_project, tagged, write_json


def _project(project_root, make_config):
    setup_project(
        project_root, {"a": "Sign in", "b": "Sign out", "c": "Home"},
        existing={"a": "Zaloguj", "b": "Wyloguj", "c": "Dom"},
    )
    cfg = make_config(
        project_root, context_dir=project_root / "context",
        flags_path=project_root / "messages" / ".flags.jsonl",
    )
    state = StateStore(cfg.state_root())
    state.record("pl", "app", "a", make_entry("Sign in", "m"))
    state.record("pl", "app", "b", make_entry("OLD ENGLISH", "m"))  # stale
    human = make_entry("Home", "m", "human")
    state.record("pl", "app", "c", human)
    state.save("pl")
    return cfg


def test_suggest_needs_a_key(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    out = dispatch_op(cfg, "suggest", {"locale": "pl"}, actor_role="Admin")
    assert out["ok"] is False


def test_suggest_returns_text_and_writes_nothing(project_root, make_config, monkeypatch) -> None:
    cfg = _project(project_root, make_config)
    monkeypatch.setattr(
        "llm_localizator.ops.suggest.provider_for_locale",
        lambda *a, **k: NullProvider(handler=tagged),
    )
    before = (cfg.state_root() / "pl.json").read_text(encoding="utf-8") if (cfg.state_root() / "pl.json").exists() else ""
    catalogue = (project_root / "messages" / "pl" / "app.json").read_text(encoding="utf-8")
    out = dispatch_op(cfg, "suggest", {"locale": "pl", "namespace": "app", "key": "a"}, actor_role="Admin")
    assert out["ok"] is True, out
    assert "Sign in" in out["data"]["text"]
    assert 0 <= out["data"]["score"] <= 1
    assert (project_root / "messages" / "pl" / "app.json").read_text(encoding="utf-8") == catalogue
    after = (cfg.state_root() / "pl.json").read_text(encoding="utf-8") if (cfg.state_root() / "pl.json").exists() else ""
    assert after == before
    assert not (cfg.history_root()).exists() or not any(cfg.history_root().rglob("*.jsonl"))


def test_suggest_explain_lists_what_fed_the_prompt(project_root, make_config, monkeypatch) -> None:
    cfg = _project(project_root, make_config)
    write_json(
        project_root / "context" / "app.json",
        {"a": {"note": "Button on the login screen", "maxChars": 20}},
    )
    monkeypatch.setattr(
        "llm_localizator.ops.suggest.provider_for_locale",
        lambda *a, **k: NullProvider(handler=tagged),
    )
    plain = dispatch_op(cfg, "suggest", {"locale": "pl", "namespace": "app", "key": "a"}, actor_role="Admin")
    assert "explain" not in plain["data"]
    out = dispatch_op(
        cfg, "suggest", {"locale": "pl", "namespace": "app", "key": "a", "explain": True},
        actor_role="Admin",
    )
    assert out["ok"], out
    why = out["data"]["explain"]
    assert why["maxChars"] == 20
    assert "login screen" in (why["context"] + why["note"])
    assert isinstance(why["trace"], list) and isinstance(why["examples"], list)
    assert "Why this result:" in out["lines"]
    blob = json.dumps(why)
    assert "http" not in blob and "api_key" not in blob.lower()


def test_translator_may_suggest_but_not_translate() -> None:
    assert role_allowed(ROLE_TRANSLATOR, "suggest")
    assert not role_allowed(ROLE_TRANSLATOR, "translate")
    assert not role_allowed(ROLE_DEVELOPER, "suggest")
    # an override cannot grant Translator translate (ADR-39)
    class Cfg:
        permission_matrix = {"translate": [True, True, True, True]}

    assert not role_allowed(ROLE_TRANSLATOR, "translate", cfg=Cfg())


def test_flag_source_is_a_ticket_not_a_translate_flag(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    first = dispatch_op(cfg, "flag-source", {"namespace": "app", "key": "a", "note": "typo"}, actor_role="Admin")
    again = dispatch_op(cfg, "flag-source", {"namespace": "app", "key": "a", "note": "typo 2"}, actor_role="Admin")
    assert first["ok"] and again["ok"]
    assert first["data"]["ticket"] == again["data"]["ticket"]  # deduped
    queue = dispatch_op(cfg, "source-review-queue", {}, actor_role="Admin")
    assert [t["key"] for t in queue["data"]["tickets"]] == ["a"]
    assert not cfg.flags_path.exists() or not cfg.flags_path.read_text(encoding="utf-8").strip()
    # a review ticket on the source locale is not target-locale work
    assert open_review_queue(cfg).open_tickets("pl") == []


def test_flag_source_unknown_key(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    assert dispatch_op(cfg, "flag-source", {"namespace": "app", "key": "zz"}, actor_role="Admin")["ok"] is False


def test_bulk_clear_stale_dry_run_then_confirm(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    preview = dispatch_op(cfg, "bulk-clear", {"stale_to_source": True, "locale": "pl"}, actor_role="Admin")
    assert preview["data"]["count"] == 1 and preview["data"]["applied"] is False
    assert StateStore(cfg.state_root()).entry("pl", "app", "b") is not None
    done = dispatch_op(cfg, "bulk-clear", {"stale_to_source": True, "locale": "pl", "confirm": True}, actor_role="Admin")
    assert done["data"]["applied"] is True
    state = StateStore(cfg.state_root())
    assert state.entry("pl", "app", "b") is None  # back in the backlog
    assert state.entry("pl", "app", "c")["status"] == "human"  # never touched
    catalogue = json.loads((project_root / "messages" / "pl" / "app.json").read_text(encoding="utf-8"))
    assert catalogue["b"] == "Wyloguj"  # old text stays as a fallback


def test_bulk_clear_purge_skips_human_verified_and_locked(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    state = StateStore(cfg.state_root())
    for key, extra in (("a", {}), ("b", {"verified_at": "2026-01-01T00:00:00Z"}), ("c", {"locked": True})):
        entry = make_entry({"a": "Sign in", "b": "Sign out", "c": "Home"}[key], "m")
        entry["translated_at"] = "2020-01-01T00:00:00Z"
        entry.update(extra)
        state.record("pl", "app", key, entry)
    state.save("pl")
    out = dispatch_op(cfg, "bulk-clear", {
        "purge_machine_older_than": 30, "locale": "pl", "confirm": True,
    }, actor_role="Admin")
    assert [k["key"] for k in out["data"]["keys"]] == ["a"]


def test_bulk_clear_needs_a_mode(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    assert dispatch_op(cfg, "bulk-clear", {}, actor_role="Admin")["ok"] is False


def test_status_by_screen_groups_and_buckets(project_root, make_config, make_catalog) -> None:
    cfg = _project(project_root, make_config)
    write_json(cfg.context_dir / "app.json", {
        "a": {"screen": "Login"}, "b": {"screen": "Login"},
    })
    rows = screen_coverage(cfg, make_catalog(cfg))
    by = {r["screen"]: r for r in rows}
    assert by["Login"]["total"] == 2 and by["Login"]["pending"] == 1
    assert by["(no screen)"]["total"] == 1 and by["(no screen)"]["pending"] == 0
    assert rows[0]["screen"] == "Login"  # least complete first
    out = dispatch_op(cfg, "status", {"by_screen": True}, actor_role="Admin")
    assert out["data"]["screens"]
