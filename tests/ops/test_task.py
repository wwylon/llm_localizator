"""Tasks: key sets with per-locale assignees; progress from state (C-009)."""

from __future__ import annotations

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.catalog.tasks import TaskStore
from llm_localizator.ops.dispatch import dispatch_op

from tests.ops.test_webui_ops import _project


def _run(cfg, **body):
    return dispatch_op(cfg, "task", body, actor_role="Admin")


def test_create_list_and_delete(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    made = _run(cfg, action="create", name="Batch", namespace="app", assign="pl=anna", due="2999-01-01")
    assert made["ok"], made
    task_id = made["data"]["tasks"][0]["id"]
    assert task_id == "T-001" and made["data"]["tasks"][0]["keys"] == 3
    listed = _run(cfg, action="list")["data"]["tasks"]
    assert listed[0]["progress"]["pl"] == {"done": 0, "total": 3} and not listed[0]["overdue"]
    assert _run(cfg, action="list", assignee="ben")["data"]["tasks"] == []
    assert _run(cfg, action="delete", id=task_id)["ok"]
    assert _run(cfg, action="list")["data"]["tasks"] == []


def test_progress_follows_verification_and_overdue(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    _run(cfg, action="create", name="Old", keys="app.a", assign="pl=anna", due="2000-01-01")
    row = _run(cfg, action="list")["data"]["tasks"][0]
    assert row["overdue"] and not row["done"]
    state = StateStore(cfg.state_root())
    entry = make_entry("Sign in", "m")
    entry["verified_at"] = "2026-01-01T00:00:00Z"
    state.record("pl", "app", "a", entry)
    state.save("pl")
    row = _run(cfg, action="list")["data"]["tasks"][0]
    assert row["done"] and not row["overdue"]


def test_unverified_filter_and_bad_input(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    assert not _run(cfg, action="create", name="x", keys="app.nope", assign="pl=anna")["ok"]
    assert not _run(cfg, action="create", name="x", namespace="app", assign="xx=anna")["ok"]
    assert not _run(cfg, action="create", name="x", namespace="app", assign="pl=a", due="soon")["ok"]
    assert not _run(cfg, action="create", name="", namespace="app", assign="pl=a")["ok"]
    made = _run(cfg, action="create", name="u", namespace="app", assign="pl=a", unverified=True)
    assert made["data"]["tasks"][0]["keys"] == 3


def test_assigned_keys_for_a_person(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    _run(cfg, action="create", name="t", keys="app.a,app.b", assign="pl=anna")
    store = TaskStore.for_project(cfg)
    assert store.assigned_keys("anna", "pl") == {"app.a", "app.b"}
    assert store.assigned_keys("anna", "de") == set() and store.assigned_keys("zed", "pl") == set()
