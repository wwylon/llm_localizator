"""Progress lines parseable by taskqueue."""

from __future__ import annotations

import re

from llm_localizator.reporting import progress_line, report_metric

_PCT_RE = re.compile(r"\((\d+(?:\.\d+)?)%\)")


def test_progress_line_matches_taskqueue_regex() -> None:
    line = progress_line(42, 897, "auth.signIn -> pl")
    assert line == "[42/897] auth.signIn -> pl (4.7%)"
    m = _PCT_RE.search(line)
    assert m is not None
    assert float(m.group(1)) == 4.7


def test_report_progress_zero_start() -> None:
    line = progress_line(0, 120, "Translating 120 key-locale pair(s)")
    assert line.startswith("[0/120]")
    assert "(0.0%)" in line


def test_report_metric_format(capsys) -> None:
    report_metric(done=5, total=10)
    out = capsys.readouterr().out.strip()
    assert out.startswith("TQ_METRIC ")
    assert '"done": 5' in out


def test_report_run_summary(capsys) -> None:
    import json

    from llm_localizator.pipeline.run_manifest import RunManifest
    from llm_localizator.reporting import report_run_summary

    manifest = RunManifest.start(command="translate", locales=["pl"], model="m")
    manifest.finish(written=2, total=2)
    report_run_summary(manifest)
    out = capsys.readouterr().out.strip()
    assert "TQ_METRIC" in out
    payload = json.loads(out.split(" ", 1)[1])
    assert payload["command"] == "translate"
    assert payload["done"] == 2
    assert "wall_s" in payload


def test_improve_progress_line_format(project_root, make_config, make_catalog, capsys) -> None:
    import re

    from llm_localizator.pipeline.improve import run_improve
    from tests.pipeline.test_translate import setup_project

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Hi"})
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        improve_model="testmodel",
    )
    catalog = make_catalog(cfg)
    from llm_localizator.catalog import ScoreStore

    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "greet", score=0.2, signals=[], text="Hi")
    scores.save("pl")
    from llm_localizator.providers import NullProvider

    result = run_improve(
        cfg, catalog, NullProvider(handler=lambda _r: "Cześć"),
        locales=["pl"], limit=1, report=print,
    )
    assert result.considered == 1
    out = capsys.readouterr().out
    assert re.search(r"\[\d+/\d+\].*\(\d+(?:\.\d+)?%\)", out)


def test_log_heartbeat_emits_during_slow_work(capsys) -> None:
    import time

    from llm_localizator.reporting import log_heartbeat

    # Ten intervals of slack: a loaded CI box can delay the heartbeat thread.
    with log_heartbeat("test work", interval_s=0.05):
        time.sleep(0.5)
    out = capsys.readouterr().out
    assert "still test work" in out
