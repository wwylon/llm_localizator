"""RunManifest finish() and analytics aggregation."""

from __future__ import annotations

import json
import time

import pytest

from llm_localizator.ops.analytics import collect_run_analytics
from llm_localizator.pipeline.run_manifest import RunManifest, iter_run_records, load_run_record


def test_finish_computes_wall_s_and_keys_per_s(tmp_path) -> None:
    manifest = RunManifest.start(command="translate", locales=["pl"], model="testmodel")
    time.sleep(0.01)
    manifest.finish(written=10, total=10)
    assert manifest.finished_at
    assert manifest.wall_s is not None
    assert manifest.wall_s > 0
    assert manifest.metrics["keys_per_s"] == pytest.approx(10 / manifest.wall_s, rel=0.05)

    path = manifest.write(tmp_path)
    loaded = load_run_record(path)
    assert loaded["metrics"]["written"] == 10
    assert "keys_per_s" in loaded["metrics"]
    assert "_t0" not in loaded


def test_legacy_manifest_loads_without_speed_fields(tmp_path) -> None:
    legacy = {
        "run_id": "abc123",
        "started_at": "2026-01-01T00:00:00Z",
        "command": "translate",
        "locales": ["pl"],
        "counts": {"written": 3},
    }
    path = tmp_path / "_runs" / "abc123.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(legacy), encoding="utf-8")
    row = load_run_record(path)
    assert row["metrics"] == {}
    assert row.get("wall_s") is None


def test_iter_run_records_newest_first(tmp_path) -> None:
    runs = tmp_path / "_runs"
    runs.mkdir()
    (runs / "a.json").write_text(json.dumps({
        "run_id": "a", "started_at": "2026-01-01T00:00:00Z", "command": "translate",
    }), encoding="utf-8")
    time.sleep(0.001)
    (runs / "b.json").write_text(json.dumps({
        "run_id": "b", "started_at": "2026-01-02T00:00:00Z", "command": "rescore",
    }), encoding="utf-8")
    records = iter_run_records(tmp_path)
    assert records[0]["run_id"] == "b"


def test_collect_run_analytics_filters(project_root, make_config) -> None:
    cfg = make_config(project_root, state_dir=project_root / ".state")
    runs = cfg.state_root() / "_runs"
    runs.mkdir(parents=True)
    (runs / "one.json").write_text(json.dumps({
        "run_id": "one",
        "started_at": "2026-06-01T00:00:00Z",
        "finished_at": "2026-06-01T01:00:00Z",
        "command": "translate",
        "locales": ["ar"],
        "model": "translategemma:4b",
        "wall_s": 100.0,
        "metrics": {"written": 50, "keys_per_s": 0.5},
    }), encoding="utf-8")
    data = collect_run_analytics(
        cfg, command="translate", locale="ar", model="translategemma:4b",
    )
    assert data["summary"]["runs"] == 1
    assert data["summary"]["keys_per_s_median"] == 0.5


def test_tq_metric_fields() -> None:
    manifest = RunManifest.start(command="rescore", locales=["pl"], model="aya")
    time.sleep(0.01)
    manifest.finish(updated=20, total=20, processed=20)
    fields = manifest.tq_metric_fields()
    assert fields["command"] == "rescore"
    assert fields["done"] == 20
    assert fields["wall_s"] >= 0
    assert manifest.metrics["items_per_s"] > 0


def test_prune_runs_prefers_started_at(tmp_path) -> None:
    from llm_localizator.pipeline import run_manifest as rm

    runs = tmp_path / "_runs"
    runs.mkdir()
    # Newer mtime but older started_at should still be pruned first.
    older = runs / "old.json"
    newer = runs / "new.json"
    older.write_text(json.dumps({
        "run_id": "old", "started_at": "2026-01-01T00:00:00Z", "command": "translate",
    }), encoding="utf-8")
    newer.write_text(json.dumps({
        "run_id": "new", "started_at": "2026-06-01T00:00:00Z", "command": "translate",
    }), encoding="utf-8")
    # Touch so older file has a newer mtime than started_at order would suggest.
    time.sleep(0.02)
    older.write_text(older.read_text(encoding="utf-8"), encoding="utf-8")
    rm._prune_runs(runs, keep=1)
    assert not older.exists()
    assert newer.exists()
