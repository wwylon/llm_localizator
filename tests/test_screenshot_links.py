"""C-012: screenshots linked to keys (ADR-102)."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog.screenshot_links import normalize_region
from llm_localizator.ops.screenshot_link import op_screenshot_link
from llm_localizator.ops.types import ScreenshotLinkRequest
from llm_localizator.projects.config import load_config


def _cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))
    (tmp_path / "ctx" / "screenshots").mkdir(parents=True)
    (tmp_path / "ctx" / "screenshots" / "home.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "ctx" / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".llm-localize.toml").write_text("\n".join([
        "[project]", 'name = "demo"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "m/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "",
        "[prompt]", 'context_dir = "ctx"', "",
    ]), encoding="utf-8")
    return load_config(tmp_path / ".llm-localize.toml")


def test_region_validation():
    assert normalize_region("0.1,0.2,0.3,0.4") == {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    assert normalize_region(None) is None
    for bad in ("0.9,0.1,0.3,0.1", "0,0,0,1", "a,b,c,d", "1,2"):
        with pytest.raises(ValueError):
            normalize_region(bad)


def test_link_list_unlink(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    res = op_screenshot_link(cfg, ScreenshotLinkRequest(
        action="link", file="screenshots/home.png", namespace="app", key="title", region="0.1,0.1,0.2,0.1"))
    assert res.ok, res.summary
    link_id = res.data["link"]["id"]
    again = op_screenshot_link(cfg, ScreenshotLinkRequest(
        action="link", file="screenshots/home.png", namespace="app", key="title", region="0.1,0.1,0.2,0.1"))
    assert again.data["link"]["id"] == link_id
    listed = op_screenshot_link(cfg, ScreenshotLinkRequest(namespace="app", key="title"))
    assert len(listed.data["links"]) == 1
    assert not op_screenshot_link(cfg, ScreenshotLinkRequest(namespace="app", key="other")).data["links"]
    assert op_screenshot_link(cfg, ScreenshotLinkRequest(action="unlink", link=link_id)).ok
    assert not op_screenshot_link(cfg, ScreenshotLinkRequest(action="unlink", link=link_id)).ok


def test_refuses_bad_files_and_regions(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    for bad in ("../x.png", "screenshots/missing.png", "notes.txt"):
        assert not op_screenshot_link(cfg, ScreenshotLinkRequest(
            action="link", file=bad, namespace="app", key="k")).ok
    assert not op_screenshot_link(cfg, ScreenshotLinkRequest(
        action="link", file="screenshots/home.png", namespace="app", key="k", region="2,2,1,1")).ok
    assert not (cfg.state_root() / "screenshot_links.json").exists()


def test_ingest_visual_attaches_link(tmp_path, monkeypatch):
    from llm_localizator.ops.ingest_visual import op_ingest_visual
    from llm_localizator.ops.types import IngestVisualRequest
    cfg = _cfg(tmp_path, monkeypatch)
    f = tmp_path / "findings.jsonl"
    f.write_text(json.dumps({
        "schema_version": 1, "screen": "home", "locale": "de", "reason": "layout_clip", "message": "cut off", "namespace": "app", "key": "title",
        "screenshot": "screenshots/home.png",
    }) + "\n", encoding="utf-8")
    res = op_ingest_visual(cfg, IngestVisualRequest(path=str(f)))
    assert res.ok, res.summary
    links = op_screenshot_link(cfg, ScreenshotLinkRequest(namespace="app", key="title")).data["links"]
    assert [l["file"] for l in links] == ["screenshots/home.png"]
