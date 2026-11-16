"""The latest [qa] crawl feeds agent-hardcoded --status and the agent prompt (D6)."""

from __future__ import annotations

import json

from llm_localizator.ops.agent_hardcoded import (
    _dynamic_text_section, _hardcoded_next_steps, latest_qa_report,
)
from llm_localizator.projects.qa_config import QaConfig


def _report(cfg, stamp="20261105T120000Z", dynamic=None):
    out = cfg.data_root() / "qa" / stamp
    out.mkdir(parents=True)
    items = dynamic or []
    (out / "summary.json").write_text(json.dumps(
        {"out_dir": str(out), "leftovers": 5, "dynamic": len(items), "layout": {"ar": {"issues": 1}}}),
        encoding="utf-8")
    (out / "dynamic_text.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return out


def test_no_report_is_none(tmp_path, make_config) -> None:
    assert latest_qa_report(make_config(tmp_path)) is None


def test_latest_report_with_dynamic_items(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    _report(cfg, "20261101T000000Z")
    newest = _report(cfg, "20261105T120000Z", dynamic=[
        {"page": "/", "selector": "pre#ladder", "text": "# Engine ladder"},
    ])
    report = latest_qa_report(cfg, items=10)
    assert report["dir"] == str(newest)
    assert report["dynamic"] == 1 and report["layout"]["ar"]["issues"] == 1
    assert report["dynamicItems"][0]["selector"] == "pre#ladder"
    assert report["ageHours"] >= 0
    section = "\n".join(_dynamic_text_section(cfg))
    assert "Server / runtime text" in section and "# Engine ladder" in section


def test_hints_for_a_qa_project(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path, name="demo", scan_adapter="raw-js", scan_src_dirs=["web"])
    cfg.qa = QaConfig(base_url="http://127.0.0.1:9")
    common = dict(cached=True, stale=False, en_xx={}, help_xx=None)
    wiring = _hardcoded_next_steps(cfg, counts={"high": 2}, **common)
    assert any(s["cmd"] == "llm-localizator check-keys demo" for s in wiring)
    assert all("--out-dir reports/" not in s["cmd"] for s in wiring)
    clear = _hardcoded_next_steps(cfg, counts={}, **common)
    assert clear[0]["cmd"] == "llm-localizator hardcoded-hunt demo --serve"
    _report(cfg, "20991231T000000Z", dynamic=[{"page": "/", "selector": "p", "text": "API text"}])
    with_report = _hardcoded_next_steps(cfg, counts={}, **common)
    assert any("dynamic_text.json" in s["cmd"] for s in with_report)
