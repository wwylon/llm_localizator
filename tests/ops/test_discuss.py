"""Per-key discussion threads: comments, mentions, resolved state (C-019)."""

from __future__ import annotations

from llm_localizator.catalog.discussions import parse_mentions
from llm_localizator.ops.dispatch import dispatch_op

from tests.ops.test_webui_ops import _project


def _run(cfg, role="Translator", **body):
    return dispatch_op(cfg, "discuss", body, actor_role=role)


def test_mentions_are_parsed() -> None:
    assert parse_mentions("hi @anna and @ben.x, mail a@b.c @anna") == ["anna", "ben.x"]


def test_add_resolve_reopen_cycle(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    made = _run(cfg, action="add", namespace="app", key="a", text="@anna formal?", by="ben")
    assert made["ok"], made
    assert _run(cfg, action="list", mention="anna")["data"]["threads"][0]["ref"] == "app.a"
    assert _run(cfg, action="list", mention="zed")["data"]["threads"] == []
    assert _run(cfg, action="resolve", namespace="app", key="a", by="anna")["ok"]
    assert _run(cfg, action="list", open_only=True)["data"]["threads"] == []
    _run(cfg, action="add", namespace="app", key="a", text="still unclear", by="ben")
    thread = _run(cfg, action="list", open_only=True)["data"]["threads"][0]
    assert thread["count"] == 2 and not thread["resolved"]
    _run(cfg, action="resolve", namespace="app", key="a")
    assert _run(cfg, action="reopen", namespace="app", key="a")["ok"]


def test_bad_input(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    assert not _run(cfg, action="add", namespace="app", key="nope", text="x")["ok"]
    assert not _run(cfg, action="add", namespace="app", key="a", text="  ")["ok"]
    assert not _run(cfg, action="resolve", namespace="app", key="a")["ok"]
    assert not _run(cfg, action="add", text="x")["ok"]
    assert not _run(cfg, action="bogus")["ok"]


def test_task_list_counts_open_threads(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    dispatch_op(cfg, "task", {"action": "create", "name": "t", "keys": "app.a,app.b",
                              "assign": "pl=anna"}, actor_role="Admin")
    _run(cfg, action="add", namespace="app", key="a", text="q")
    _run(cfg, action="add", namespace="app", key="b", text="q")
    _run(cfg, action="resolve", namespace="app", key="b")
    rows = dispatch_op(cfg, "task", {"action": "list"}, actor_role="Admin")["data"]["tasks"]
    assert rows[0]["open_threads"] == 1
