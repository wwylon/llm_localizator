"""``migrate-state`` -- rewriting derived fields after a format change.

The safety property under test: a migration must recompute ``structure_sig`` and
touch nothing else. If it disturbed ``src_sha``, every key would be marked stale
and the next run would retranslate the entire catalogue.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.cli.main import main
from llm_localizator.core.hash import src_hash, structure_signature

from .conftest import write_json

CONFIG = """
[project]
name = "demo"
data_home = "project"   # state beside the config, where this test reads it (ADR-112 default is the engine home)

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]

[state]
dir = "messages/.state"
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json",
               {"greet": "Hello {name}", "bye": "Goodbye"})
    write_json(tmp_path / "messages" / "pl" / "app.json",
               {"greet": "Witaj {name}", "bye": "Zegnaj"})

    store = StateStore(tmp_path / "messages" / ".state")
    for key, value in (("greet", "Hello {name}"), ("bye", "Goodbye")):
        entry = make_entry(value, "testmodel")
        entry["structure_sig"] = "stale00000000"   # as if written by version 1
        store.record("pl", "app", key, entry)
    store.save("pl")
    return tmp_path


def run(args: list[str], project: Path) -> int:
    return main([*args, "--config", str(project / ".llm-localize.toml")])


def state_of(project: Path) -> dict:
    return json.loads((project / "messages" / ".state" / "pl.json").read_text(encoding="utf-8"))


def test_rewrites_stale_signatures(project: Path, capsys) -> None:
    assert run(["migrate-state"], project) == 0
    entries = state_of(project)
    assert entries["app.greet"]["structure_sig"] == structure_signature("Hello {name}")
    assert entries["app.bye"]["structure_sig"] == structure_signature("Goodbye")


def test_leaves_every_other_field_untouched(project: Path) -> None:
    """The critical safety property: src_sha must survive, or the next run
    retranslates the whole catalogue."""
    before = state_of(project)
    run(["migrate-state"], project)
    after = state_of(project)

    for key in before:
        for field in ("src_sha", "translated_at", "model", "status"):
            assert after[key][field] == before[key][field], f"{key}.{field} changed"


def test_src_sha_still_matches_the_source(project: Path) -> None:
    run(["migrate-state"], project)
    assert state_of(project)["app.greet"]["src_sha"] == src_hash("Hello {name}")


def test_dry_run_writes_nothing(project: Path, capsys) -> None:
    before = state_of(project)
    assert run(["migrate-state", "--dry-run"], project) == 0
    assert state_of(project) == before
    assert "Dry run" in capsys.readouterr().out


def test_second_run_is_a_noop(project: Path, capsys) -> None:
    run(["migrate-state"], project)
    capsys.readouterr()
    run(["migrate-state"], project)
    assert "rewrote 0 of" in capsys.readouterr().out


def test_orphaned_entries_are_reported_not_deleted(project: Path, capsys) -> None:
    """An entry whose source key is gone cannot be recomputed. Pruning state is
    a separate decision, so migration must not make it silently."""
    store = StateStore(project / "messages" / ".state")
    store.load("pl")["app.removed"] = make_entry("Gone", "testmodel")
    store.save("pl")

    run(["migrate-state"], project)

    assert "app.removed" in state_of(project)
    assert "orphaned" in capsys.readouterr().out


def test_migration_clears_structural_staleness(project: Path) -> None:
    """End to end: before migration every key reads as structurally stale;
    after, none does."""
    from llm_localizator.catalog import is_structurally_stale

    store = StateStore(project / "messages" / ".state")
    assert is_structurally_stale("Hello {name}", store.entry("pl", "app", "greet"))

    run(["migrate-state"], project)

    fresh = StateStore(project / "messages" / ".state")
    assert not is_structurally_stale("Hello {name}", fresh.entry("pl", "app", "greet"))


def test_project_without_explicit_state_dir_uses_default(tmp_path: Path) -> None:
    # No [state] section — defaults to <root>/.llm-state, migrate-state still works.
    (tmp_path / ".llm-localize.toml").write_text(
        CONFIG.replace('\n[state]\ndir = "messages/.state"\n', ""), encoding="utf-8"
    )
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})
    assert run(["migrate-state"], tmp_path) == 0  # succeeds; default state dir created


def test_stamp_provider_fills_missing_channel(project: Path, capsys) -> None:
    store = StateStore(project / "messages" / ".state")
    legacy = {
        "src_sha": src_hash("Hello {name}"),
        "structure_sig": structure_signature("Hello {name}"),
        "translated_at": "2026-01-01T00:00:00Z",
        "model": "claude-haiku-4-5",
        "status": "machine",
    }
    store.record("pl", "app", "greet", legacy)
    store.save("pl")

    assert run(["migrate-state", "--stamp-provider"], project) == 0
    out = capsys.readouterr().out
    assert "provider" in out.lower() or "stamp" in out.lower()
    entry = state_of(project)["app.greet"]
    assert entry["provider"] == "anthropic"
    assert entry["model"] == "claude-haiku-4-5"
