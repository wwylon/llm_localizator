"""Draft store: create keeps, accept writes a human edit, reject drops (C-018)."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.catalog.drafts import DraftStore, draft_id
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.permissions import ROLE_DEVELOPER, ROLE_TRANSLATOR, role_allowed


def _cfg(project_root, make_config):
    from tests.ops.test_webui_ops import _project  # reuse the small fixture project

    return _project(project_root, make_config)


def _seed(cfg, text="Zapisz", source=None):
    from llm_localizator.catalog import build_catalog

    cat = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    src = source if source is not None else cat.load(cfg.source_locale, "app")["a"]
    DraftStore.for_project(cfg).put("pl", "app", "a", text=text, score=0.9, model="m", source=src, by="t")
    return cat


def test_draft_store_replaces_and_discards(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts.json")
    store.put("pl", "app", "a", text="one")
    store.put("pl", "app", "a", text="two")
    assert store.get(draft_id("pl", "app", "a"))["text"] == "two"
    assert store.discard(draft_id("pl", "app", "a")) and not store.discard("missing")
    assert json.loads((tmp_path / "drafts.json").read_text("utf-8"))["items"] == {}


def test_accept_writes_a_human_edit_and_removes_the_draft(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    cat = _seed(cfg)
    out = dispatch_op(cfg, "draft", {"action": "accept", "locale": "pl", "keys": "app.a"}, actor_role="Admin")
    assert out["data"]["written"] == ["app.a"], out
    assert cat.load("pl", "app")["a"] == "Zapisz"
    assert DraftStore.for_project(cfg).get(draft_id("pl", "app", "a")) is None


def test_stale_draft_is_listed_and_refused(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    cat = _seed(cfg, source="an older English text")
    listed = dispatch_op(cfg, "draft", {"action": "list"}, actor_role="Admin")
    assert listed["data"]["drafts"][0]["stale"] is True
    before = cat.load("pl", "app").get("a")
    out = dispatch_op(cfg, "draft", {"action": "accept", "locale": "pl", "keys": "app.a"}, actor_role="Admin")
    assert out["data"]["written"] == [] and "source changed" in out["data"]["skipped"][0]
    assert cat.load("pl", "app").get("a") == before


def test_reject_drops_without_writing(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    cat = _seed(cfg)
    before = cat.load("pl", "app").get("a")
    out = dispatch_op(cfg, "draft", {"action": "reject", "locale": "pl", "key": "a", "namespace": "app"}, actor_role="Admin")
    assert out["data"]["rejected"] == ["app.a"]
    assert cat.load("pl", "app").get("a") == before


def test_roles() -> None:
    assert role_allowed(ROLE_TRANSLATOR, "draft") and not role_allowed(ROLE_DEVELOPER, "draft")


def _mark_human(cfg) -> None:
    from llm_localizator.pipeline.recording import provenance_stores

    stores = provenance_stores(cfg)
    entry = stores.state.entry("pl", "app", "a")
    if entry is None:
        stores.state.load("pl")["app.a"] = entry = {}
    entry["status"] = "human"
    stores.state.save_all(["pl"])


def test_accept_skips_a_human_edit_unless_confirmed(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    cat = _seed(cfg)
    _mark_human(cfg)
    before = cat.load("pl", "app").get("a")
    body = {"action": "accept", "locale": "pl", "keys": "app.a"}
    out = dispatch_op(cfg, "draft", body, actor_role="Admin")
    assert out["data"]["written"] == [] and "human-edited" in out["data"]["skipped"][0]
    assert cat.load("pl", "app").get("a") == before
    assert DraftStore.for_project(cfg).get(draft_id("pl", "app", "a")) is not None
    out = dispatch_op(cfg, "draft", {**body, "confirm": True}, actor_role="Admin")
    assert out["data"]["written"] == ["app.a"], out
    assert cat.load("pl", "app")["a"] == "Zapisz"
