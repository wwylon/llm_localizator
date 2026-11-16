"""hardcoded-hunt path resolution and skip-crawl path (hermetic)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.ops.hardcoded_hunt import op_hardcoded_hunt, resolve_experiments_dir
from llm_localizator.ops.types import OpResult
from tests.conftest import setup_project


ENGINE_EXP = Path(__file__).resolve().parents[2] / "experiments" / "hardcoded_visible"


@pytest.mark.skipif(not ENGINE_EXP.is_dir(), reason="needs experiments/hardcoded_visible (dev checkout only)")
def test_resolve_experiments_dir_ignores_the_project_copy(tmp_path, make_config, monkeypatch) -> None:
    monkeypatch.delenv("LLM_LOCALIZE_EXPERIMENTS", raising=False)
    setup_project(tmp_path, {"a": "A"})
    planted = tmp_path / "experiments" / "hardcoded_visible"
    planted.mkdir(parents=True)
    (planted / "crawl.py").write_text("# consumer code\n", encoding="utf-8")
    (planted / "intersect.py").write_text("# consumer code\n", encoding="utf-8")
    cfg = make_config(tmp_path)
    assert resolve_experiments_dir(cfg) == ENGINE_EXP


@pytest.mark.skipif(not ENGINE_EXP.is_dir(), reason="needs experiments/hardcoded_visible (dev checkout only)")
def test_qa_project_runs_the_config_driven_crawl(tmp_path, make_config, monkeypatch) -> None:
    from llm_localizator.projects.qa_config import QaConfig

    setup_project(tmp_path, {"a": "A"})
    cfg = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json")
    (tmp_path / "locales").mkdir(exist_ok=True)
    (tmp_path / "locales" / "en.json").write_text('{"a": "A"}', encoding="utf-8")
    cfg.qa = QaConfig(base_url="http://127.0.0.1:9")
    calls: list[list[str]] = []

    def fake_run(script, args, *, cwd):
        calls.append([Path(script).name, *args])
        out = Path(args[args.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text('{"leftovers": 3, "dynamic": 1, "layout": {}}', encoding="utf-8")
        return 0, "3 leftovers (1 dynamic)"

    monkeypatch.setattr("llm_localizator.ops.hardcoded_hunt._run_script", fake_run)
    out = op_hardcoded_hunt(cfg, skip_static=True)
    assert out.ok, out.summary
    assert [c[0] for c in calls] == ["crawl.py"]  # no dogfood intersect
    assert "--no-serve" in calls[0] and "--project" in calls[0]
    report = Path(out.data["qa_report"])
    assert report.parent == Path(cfg.data_root()) / "qa"
    assert out.data["qa_summary"]["dynamic"] == 1
    serve = op_hardcoded_hunt(cfg, skip_static=True, no_serve=False)
    assert serve.ok and "--no-serve" not in calls[-1]


def test_hardcoded_hunt_skip_crawl_runs_pseudo(tmp_path, make_config, monkeypatch) -> None:
    setup_project(tmp_path, {"greeting": "Hello"})
    locales = tmp_path / "locales"
    locales.mkdir(exist_ok=True)
    (locales / "en.json").write_text(json.dumps({"greeting": "Hello"}), encoding="utf-8")
    cfg = make_config(
        tmp_path,
        catalog_format="json-flat",
        catalog_path="locales/{locale}.json",
        qa_locales=["en-XX"],
    )

    def fake_pseudo(c, req):
        path = c.root / "locales" / "en-XX.json"
        path.write_text(json.dumps({"greeting": "XXXXX"}), encoding="utf-8")
        return OpResult(
            ok=True, exit_code=0, command="pseudo",
            summary="wrote 1", lines=["wrote 1"], data={},
        )

    def fake_static(c, req):
        return OpResult(
            ok=True, exit_code=0, command="agent-hardcoded",
            summary="0 hardcoded", lines=["0 hardcoded"], data={"hits": []},
        )

    monkeypatch.setattr("llm_localizator.ops.hardcoded_hunt.op_pseudo", fake_pseudo)
    monkeypatch.setattr("llm_localizator.ops.hardcoded_hunt.op_agent_hardcoded", fake_static)
    out = op_hardcoded_hunt(cfg, skip_crawl=True)
    assert out.ok
    assert out.exit_code == 0
    assert (tmp_path / "locales" / "en-XX.json").is_file()
    steps = {s["step"]: s for s in out.data["steps"]}
    assert steps["pseudo"]["ok"] is True
    assert steps["crawl"].get("skipped") is True
