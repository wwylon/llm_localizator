"""find-replace: preview and apply (C-020)."""

from __future__ import annotations

from llm_localizator.ops.dispatch import dispatch_op

from tests.conftest import setup_project

SRC = {"a": "Account page", "b": "Account settings", "c": "Delete everything"}


def _cfg(project_root, make_config):
    setup_project(project_root, SRC, existing={"a": "Strona Konto", "b": "Ustawienia konto", "c": "Usun wszystko"})
    return make_config(project_root)


def test_preview_is_case_insensitive_and_writes_nothing(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    out = dispatch_op(cfg, "find-replace", {"locale": "pl", "find": "konto", "replace": "Profil"}, actor_role="Admin")
    assert out["ok"], out
    rows = {r["key"]: r for r in out["data"]["rows"]}
    assert set(rows) == {"a", "b"}
    assert rows["a"]["after"] == "Strona Profil"
    assert out["data"]["applied"] is False


def test_confirm_changes_only_named_keys(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    body = {"locale": "pl", "find": "Konto", "replace": "Profil", "case_sensitive": True, "keys": ["app.a"], "confirm": True}
    out = dispatch_op(cfg, "find-replace", body, actor_role="Admin")
    assert out["data"]["written"] == ["app.a"], out
    again = dispatch_op(cfg, "find-replace", {"locale": "pl", "find": "Profil"}, actor_role="Admin")
    assert [r["key"] for r in again["data"]["rows"]] == ["a"]


def test_empty_find_is_rejected(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    out = dispatch_op(cfg, "find-replace", {"locale": "pl", "find": ""}, actor_role="Admin")
    assert out["ok"] is False
