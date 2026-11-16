"""W5 findings page: hits of the stored scan with decision ids, without scanning."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.catalog.scan_decisions import ScanDecisions, hit_id
from llm_localizator.ops.agent_hardcoded import cached_hit_rows
from llm_localizator.projects.config import load_config

BASE = (
    '[project]\nname = "demo"\nsource_locale = "en"\n\n'
    '[catalog]\nformat = "json-flat"\npath = "{locale}.json"\n\n'
    '[locales]\ntargets = ["pl"]\n'
)


def seed_scan_cache(cfg, hits: list[dict]) -> None:
    path = cfg.state_root() / "scan_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"key": "k", "hits": hits, "ts": "2026-11-14T00:00:00+00:00",
                                "filesScanned": 3}), encoding="utf-8")


def test_no_cache_is_an_empty_state(tmp_path: Path) -> None:
    (tmp_path / ".llm-localize.toml").write_text(BASE, encoding="utf-8")
    cfg = load_config(tmp_path / ".llm-localize.toml")
    assert cached_hit_rows(cfg) == {"cached": False, "ts": None, "hits": [], "filesScanned": 0}


def test_hits_carry_decision_ids(tmp_path: Path) -> None:
    (tmp_path / ".llm-localize.toml").write_text(BASE, encoding="utf-8")
    cfg = load_config(tmp_path / ".llm-localize.toml")
    hits = [
        {"file": "src/a.js", "line": 3, "text": "Save changes", "confidence": "high"},
        {"file": "src/b.js", "line": 9, "text": "Cancel", "confidence": "low"},
    ]
    seed_scan_cache(cfg, hits)
    ScanDecisions.for_project(cfg).decide(hit_id("src/b.js", "Cancel"), "ignored")
    out = cached_hit_rows(cfg)
    assert out["cached"] and out["filesScanned"] == 3
    by_text = {h["text"]: h for h in out["hits"]}
    assert by_text["Save changes"]["id"] == hit_id("src/a.js", "Save changes")
    assert by_text["Save changes"]["decision"] is None
    # Ignored hits stay listed so the page can show and undo them.
    assert by_text["Cancel"]["decision"] == "ignored"


def test_hits_route_and_page_are_registered() -> None:
    from llm_localizator.web.get_policy import policy_for_get
    from llm_localizator.web.server import _Handler
    from llm_localizator.web.shell import route_for_path

    assert policy_for_get("/api/scan/hits") == "auth"
    assert _Handler._GET_ROUTES["/api/scan/hits"] == "_get_scan_hits"
    assert route_for_path("/app/hardcoded").id == "hardcoded"
