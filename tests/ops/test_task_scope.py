"""Tasks-only contributing: a Translator writes only keys a task assigns (C-029)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.catalog.drafts import DraftStore
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.permissions import task_scope_denied
from llm_localizator.projects.config import ConfigError, load_config

from tests.ops.test_webui_ops import _project


def _task(cfg, **body):
    return dispatch_op(cfg, "task", {"action": "create", **body}, actor_role="Admin")


def test_flag_off_allows_everything(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    assert task_scope_denied(cfg, "Translator", "anna", "pl", ["app.a"]) == ""


def test_translator_limited_to_assigned_keys(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    cfg.tasks_only = True
    _task(cfg, name="t", keys="app.a", assign="pl=anna")
    assert task_scope_denied(cfg, "Translator", "anna", "pl", ["app.a"]) == ""
    assert "not assigned" in task_scope_denied(cfg, "Translator", "anna", "pl", ["app.b"])
    assert task_scope_denied(cfg, "Translator", "ben", "pl", ["app.a"])
    assert task_scope_denied(cfg, "Translator", None, "pl", ["app.a"])
    assert task_scope_denied(cfg, "Translator", "anna", "de", ["app.a"])


def test_other_roles_are_unaffected(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    cfg.tasks_only = True
    for role in ("Admin", "Supervisor", "Developer"):
        assert task_scope_denied(cfg, role, "anna", "pl", ["app.a"]) == ""


def test_draft_accept_is_refused_outside_the_task(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    cfg.tasks_only = True
    _task(cfg, name="t", keys="app.a", assign="pl=anna")
    DraftStore.for_project(cfg).put("pl", "app", "b", text="x", source="Sign out")
    out = dispatch_op(
        cfg, "draft", {"action": "accept", "locale": "pl", "keys": "app.b"},
        actor_role="Translator", actor_name="anna",
    )
    assert out["ok"] is False and out["exit_code"] == 77 and "not assigned" in out["error"]
    assert DraftStore.for_project(cfg).get("pl:app.b") is not None


def test_config_flag_parses_and_rejects_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / ".llm-localize.toml"
    base = (
        '[project]\nname = "demo"\nsource_locale = "en"\n\n'
        '[catalog]\nformat = "json-nested"\npath = "messages/{locale}/{namespace}.json"\n\n'
        '[locales]\ntargets = ["pl"]\n\n[provider]\nkind = "null"\n\n[prompt]\nfamily = "chat"\n'
    )
    (tmp_path / "messages" / "en").mkdir(parents=True)
    path.write_text(base + "\n[tasks]\ncontribute_in_tasks_only = true\n", encoding="utf-8")
    assert load_config(path).tasks_only is True
    path.write_text(base + "\n[tasks]\nnope = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
