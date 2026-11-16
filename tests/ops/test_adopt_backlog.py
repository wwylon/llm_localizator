"""Tests for adopt + agent-backlog ops."""

from __future__ import annotations

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.cli.main import build_parser
from llm_localizator.ops import build_commands_manifest, dispatch_op
from llm_localizator.ops.adopt import op_adopt
from llm_localizator.ops.agent_backlog import op_agent_backlog
from llm_localizator.ops.catalogue_gaps import iter_catalogue_gaps
from llm_localizator.ops.types import AdoptRequest, AgentBacklogRequest, StatusRequest
from llm_localizator.ops.status import op_status

from tests.pipeline.test_translate import setup_project
from tests.conftest import write_json


def test_manifest_includes_adopt_and_agent_backlog() -> None:
    commands = build_commands_manifest(build_parser())["commands"]
    assert "adopt" in commands
    assert "agent-backlog" in commands


def test_catalogue_gaps_classify_reasons(project_root, make_config) -> None:
    setup_project(
        project_root,
        {"a": "A", "b": "B", "c": "C", "d": "D"},
        existing={"a": "Aa", "b": "", "c": "Cc"},
    )
    cfg = make_config(project_root)
    store = StateStore(cfg.state_dir)
    # c has catalogue + matching state
    store.record("pl", "app", "c", make_entry("C", "llama", "machine", provider="ollama"))
    # d missing from catalogue; leave no state
    # a is no_state (value present, no entry)
    store.save("pl")

    gaps = {g.key: g.reason for g in iter_catalogue_gaps(cfg, locales=["pl"])}
    assert gaps["a"] == "no_state"
    assert gaps["b"] == "empty"
    assert gaps["d"] == "missing"
    assert "c" not in gaps


def test_adopt_stamps_no_state_dry_run_writes_nothing(project_root, make_config) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    result = op_adopt(cfg, AdoptRequest(locales=["pl"], dry_run=True))
    assert result.ok
    assert result.data["wouldAdopt"] == 1
    assert not (cfg.state_dir / "pl.json").exists()


def test_adopt_stamps_agent_provenance(project_root, make_config) -> None:
    setup_project(
        project_root,
        {"greet": "Hello", "bye": "Bye"},
        existing={"greet": "Cześć", "bye": "Pa"},
    )
    cfg = make_config(project_root)
    # bye already has state — must not be rewritten
    store = StateStore(cfg.state_dir)
    prior = make_entry("Bye", "llama3.2", "machine", provider="ollama")
    store.record("pl", "app", "bye", prior)
    store.save("pl")

    result = op_adopt(cfg, AdoptRequest(locales=["pl"]))
    assert result.ok
    assert result.data["adopted"] == 1

    store2 = StateStore(cfg.state_dir)
    greet = store2.entry("pl", "app", "greet")
    assert greet is not None
    assert greet["provider"] == "agent"
    assert greet["model"] == "cursor-agent"
    assert greet["status"] == "agent"
    assert greet["verified_by"] == "cursor-agent"
    assert greet.get("verified_at")

    bye = store2.entry("pl", "app", "bye")
    assert bye["model"] == "llama3.2"
    assert bye["provider"] == "ollama"

    status = op_status(cfg, StatusRequest())
    pl = next(r for r in status.data["locales"] if r["locale"] == "pl")
    assert pl["missing"] == 0
    assert pl["translated"] == 2


def test_adopt_skips_empty_and_missing(project_root, make_config) -> None:
    setup_project(
        project_root,
        {"a": "A", "b": "B", "c": "C"},
        existing={"a": "Aa", "b": "  "},
    )
    cfg = make_config(project_root)
    result = op_adopt(cfg, AdoptRequest(locales=["pl"]))
    assert result.data["adopted"] == 1
    store = StateStore(cfg.state_dir)
    assert store.entry("pl", "app", "a") is not None
    assert store.entry("pl", "app", "b") is None
    assert store.entry("pl", "app", "c") is None


def test_agent_backlog_prompt_contains_en_and_reasons(project_root, make_config) -> None:
    setup_project(
        project_root,
        {"greet": "Hello", "farewell": "Goodbye"},
        existing={"greet": "Cześć"},
    )
    cfg = make_config(project_root)
    result = op_agent_backlog(
        cfg,
        AgentBacklogRequest(locales=["pl"], fmt="prompt"),
    )
    assert result.ok
    text = "\n".join(result.lines)
    assert "Localization backlog" in text
    assert "Hello" in text or "EN:" in text
    assert "farewell" in text
    assert "reason: missing" in text or "reason: no_state" in text
    assert "llm-localizator adopt" in text
    assert "messages/pl/{namespace}.json" in text or "messages/pl/" in text


def test_agent_backlog_json_and_stale(project_root, make_config) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    store = StateStore(cfg.state_dir)
    # Stale: state for old English
    store.record(
        "pl", "app", "greet",
        make_entry("Old Hello", "llama", "machine", provider="ollama"),
    )
    store.save("pl")

    # Update English source
    write_json(project_root / "messages" / "en" / "app.json", {"greet": "Hello!"})

    result = op_agent_backlog(
        cfg,
        AgentBacklogRequest(locales=["pl"], fmt="json", include_existing=True),
    )
    assert result.ok
    keys = result.data["keys"]
    assert len(keys) == 1
    assert keys[0]["reason"] == "stale"
    assert keys[0]["target"] == "Cześć"
    assert result.data["prompt"]


def test_dispatch_adopt_and_agent_backlog(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"}, existing={"a": "Aa"})
    cfg = make_config(project_root)
    dry = dispatch_op(cfg, "adopt", {"locales": ["pl"], "dry_run": True}, actor_role="Admin")
    assert dry["command"] == "adopt"
    assert dry["ok"] is True
    assert dry["data"]["wouldAdopt"] == 1

    backlog = dispatch_op(cfg, "agent-backlog", {"locales": ["pl"], "format": "json"}, actor_role="Admin")
    assert backlog["command"] == "agent-backlog"
    assert backlog["ok"] is True
    assert backlog["data"]["count"] >= 1
