"""ADR-112: engine sidecars default under ~/.llm_localize/data/<name>/."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.projects.config import CONFIG_FILENAME, ConfigError, load_config

MINIMAL = """
[project]
name = "demo"

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]
"""


def _write(root: Path, body: str = MINIMAL) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / CONFIG_FILENAME
    path.write_text(body, encoding="utf-8")
    return path


def test_default_data_home_is_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(home))
    cfg = load_config(_write(tmp_path / "proj"))
    assert cfg.data_home == "engine"
    assert cfg.data_root() == home / "data" / "demo"
    assert cfg.state_root() == home / "data" / "demo" / ".llm-state"
    assert cfg.history_root() == home / "data" / "demo" / ".llm-history"
    assert cfg.scores_root() == home / "data" / "demo" / ".llm-scores"
    assert cfg.tm_root() == home / "data" / "demo" / ".llm-tm"
    assert cfg.review_root() == home / "data" / "demo" / ".llm-review"
    assert cfg.budget_root() == home / "data" / "demo" / ".llm-budget"
    assert cfg.scan_out_root() == home / "data" / "demo" / ".usage"
    assert cfg.documents_state_root() == home / "data" / "demo" / "documents-state"
    assert cfg.flags_path == home / "data" / "demo" / ".llm-flags.jsonl"


def test_project_data_home_keeps_sidecars_in_repo(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    body = MINIMAL.replace(
        'name = "demo"',
        'name = "demo"\ndata_home = "project"',
    )
    cfg = load_config(_write(root, body))
    assert cfg.data_home == "project"
    assert cfg.data_root() == root
    assert cfg.state_root() == root / ".llm-state"
    assert cfg.tm_root() == root / ".llm-tm"
    assert cfg.review_root() == root / ".llm-review"
    assert cfg.budget_root() == root / ".llm-budget"
    assert cfg.scan_out_root() is None
    assert cfg.documents_state_root(root / "content" / "legal") == root / "content" / "legal" / ".state"


def test_absolute_sidecar_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(home))
    abs_state = tmp_path / "elsewhere" / "state"
    body = MINIMAL + f'\n[state]\ndir = "{abs_state.as_posix()}"\n'
    cfg = load_config(_write(tmp_path / "proj", body))
    assert cfg.state_root() == abs_state


def test_relative_sidecar_override_uses_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(home))
    body = MINIMAL + '\n[state]\ndir = "custom-state"\n'
    cfg = load_config(_write(tmp_path / "proj", body))
    assert cfg.state_root() == home / "data" / "demo" / "custom-state"


def test_catalog_and_glossary_stay_on_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(home))
    root = tmp_path / "proj"
    body = MINIMAL + '\n[prompt]\nglossary = "messages/glossary.json"\ncontext_dir = "messages/context"\n'
    cfg = load_config(_write(root, body))
    assert cfg.root == root
    assert "messages/{locale}" in cfg.catalog_path
    assert cfg.glossary_path == root / "messages" / "glossary.json"
    assert cfg.context_dir == root / "messages" / "context"
    assert cfg.state_root().is_relative_to(home / "data" / "demo")


def test_unknown_data_home_rejected(tmp_path: Path) -> None:
    body = MINIMAL.replace('name = "demo"', 'name = "demo"\ndata_home = "cloud"')
    with pytest.raises(ConfigError, match="data_home"):
        load_config(_write(tmp_path, body))
