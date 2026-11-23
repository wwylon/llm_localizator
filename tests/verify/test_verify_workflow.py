"""End-to-end check of the verify workflow on small synthetic projects."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from llm_localizator.verify import PROFILES, exit_code_for, run_verify

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "mini"


def _verdicts(results):
    return {r.stage: r.verdict for r in results}


def test_quick_on_mini_never_modifies_source(tmp_path):
    before = {p: p.read_bytes() for p in MINI.rglob("*") if p.is_file()}
    run_dir, results = run_verify(MINI, out=tmp_path)
    assert {r.stage for r in results} == set(PROFILES["quick"])
    assert _verdicts(results)["S8"] == "pass"
    assert _verdicts(results)["S4"] == "pass"
    assert all(p.read_bytes() == data for p, data in before.items())
    assert (run_dir / "VERIFY.md").is_file()
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert len(record["stages"]) == len(results)


def test_greenfield_project_degrades_not_crashes(tmp_path):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "app.py").write_text('print("Welcome to the dashboard")\n', encoding="utf-8")
    _, results = run_verify(proj, out=tmp_path / "out")
    verdicts = _verdicts(results)
    assert verdicts["S1"] == "degraded"
    assert verdicts["S2"] == "skipped"
    assert verdicts["S8"] == "pass"
    assert "fail" not in verdicts.values()
    assert exit_code_for(results) == 2


def test_resume_skips_finished_stages(tmp_path):
    run_dir, first = run_verify(MINI, out=tmp_path)
    calls = []

    def boom(ctx):
        calls.append(1)
        raise AssertionError("stage re-ran")

    _, second = run_verify(
        MINI, out=tmp_path, resume=run_dir.name,
        stages_override={s: ("x", boom) for s in PROFILES["quick"]},
    )
    assert not calls
    assert _verdicts(second) == _verdicts(first)


def test_engine_write_to_source_is_flagged(tmp_path):
    proj = tmp_path / "proj"
    shutil.copytree(MINI, proj)
    (proj / "src").mkdir(exist_ok=True)
    (proj / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    def tamper(ctx):
        from llm_localizator.verify.runner import StageResult

        (ctx.ws / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
        return StageResult("S0", "tamper", "pass")

    _, results = run_verify(
        proj, out=tmp_path / "out", only=["S0"],
        stages_override={"S0": ("tamper", tamper)},
    )
    assert results[0].verdict == "fail"


def test_unknown_profile_rejected(tmp_path):
    with pytest.raises(ValueError):
        run_verify(MINI, profile="bogus", out=tmp_path)


def test_s6_oob_probe_passes_on_synth_project_and_restores_catalogue(tmp_path):
    from tests.synth.factory import build_project

    proj = tmp_path / "proj"
    proj.mkdir()
    build_project(proj)
    target = proj / "messages" / "pl" / "app.json"
    before = target.read_bytes()
    _, results = run_verify(proj, profile="standard", only=["S0", "S1", "S6"], out=tmp_path / "out")
    assert _verdicts(results)["S6"] == "pass", [r.notes for r in results]
    assert target.read_bytes() == before


@pytest.mark.slow
def test_deep_profile_runs_reports_and_locale_stages(tmp_path):
    _, results = run_verify(MINI, profile="deep", locales="plurals,unprofiled", out=tmp_path)
    by_id = {r.stage: r for r in results}
    assert by_id["S5"].verdict in ("pass", "degraded")
    assert by_id["S7"].verdict == "skipped"
    assert by_id["S9"].metrics["locales"] >= 8
    assert by_id["S8"].verdict == "pass"
