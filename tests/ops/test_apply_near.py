"""apply-near: copy an edit onto similar keys (C-010)."""

from __future__ import annotations

from llm_localizator.ops.dispatch import dispatch_op

from tests.conftest import setup_project

SRC = {"a": "Save your changes now", "b": "Save your changes", "c": "Delete everything", "d": "Save your change now"}


def _cfg(project_root, make_config):
    setup_project(project_root, SRC, existing={"a": "Zapisz zmiany teraz", "d": "Zapisz teraz"})
    return make_config(project_root)


def test_preview_lists_near_keys_and_writes_nothing(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    out = dispatch_op(cfg, "apply-near", {"locale": "pl", "namespace": "app", "key": "a", "min_similarity": 0.75}, actor_role="Admin")
    assert out["ok"], out
    keys = {c["key"]: c for c in out["data"]["candidates"]}
    assert set(keys) == {"b", "d"}  # "c" is too different
    assert out["data"]["applied"] is False


def test_confirm_writes_only_named_keys(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    body = {"locale": "pl", "namespace": "app", "key": "a", "keys": ["app.b"], "confirm": True, "min_similarity": 0.75}
    out = dispatch_op(cfg, "apply-near", body, actor_role="Admin")
    assert out["data"]["written"] == ["app.b"], out
    again = dispatch_op(cfg, "apply-near", {"locale": "pl", "namespace": "app", "key": "a", "min_similarity": 0.75}, actor_role="Admin")
    rows = {c["key"]: c for c in again["data"]["candidates"]}
    assert rows["b"]["skip"] == "human" and rows["b"]["current"] == "Zapisz zmiany teraz"
    assert rows["d"]["skip"] is None


def test_needs_a_translated_key(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    out = dispatch_op(cfg, "apply-near", {"locale": "pl", "namespace": "app", "key": "c"}, actor_role="Admin")
    assert out["ok"] is False
