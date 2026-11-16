"""W3 queue page: read-only queue payload and the queue-engine blueprint rewrite (tmp_path projects only)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml as pyyaml

from llm_localizator.ops.queue import blueprint_jobs, op_queue_engine, queue_payload, tq_home
from llm_localizator.projects.config import load_config
from llm_localizator.projects.taskqueue import blueprint_filename, generate_blueprint

BASE = (
    '[project]\nname = "demo"\nsource_locale = "en"\n\n'
    '[catalog]\nformat = "json-flat"\npath = "{locale}.json"\n\n'
    '[locales]\ntargets = ["pl"]\n\n'
    '[locales.models]\ndefault = "aya-expanse:8b"\n\n'
)
CLOUD = '[privacy]\nallow_cloud = true\n\n[budget]\nmonthly_usd = 5\n'


@pytest.fixture(autouse=True)
def _no_env_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LLM_LOCALIZE_ENGINE", raising=False)
    monkeypatch.setenv("TQDAEMON_HOME", str(tmp_path / "tqhome"))
    monkeypatch.delenv("TASKQUEUE_HOME", raising=False)


def _project(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / ".llm-localize.toml"
    path.write_text(BASE + extra, encoding="utf-8")
    return path


def _write_blueprints(cfg, jobs) -> Path:
    out = cfg.root / "experiments" / "operator_queue"
    out.mkdir(parents=True, exist_ok=True)
    for job, loc in jobs:
        (out / blueprint_filename(job, loc)).write_text(generate_blueprint(cfg, job, locale=loc), encoding="utf-8")
    return out


def _make_db(home: Path, rows: list[tuple]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(home / "queue.db")
    conn.execute("CREATE TABLE tasks (project TEXT, task_id TEXT, status TEXT, args TEXT, resources TEXT, "
                 "yaml_source TEXT, last_run_id INTEGER)")
    conn.execute("CREATE TABLE runs (run_id INTEGER, status TEXT, finished_at TEXT, last_log_line TEXT)")
    conn.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,?,?)", rows)
    conn.execute("INSERT INTO runs VALUES (7, 'completed', '2026-11-14T01:00:00', 'done (100%)')")
    conn.commit()
    conn.close()


def test_tq_home_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TQDAEMON_HOME", str(tmp_path / "a"))
    monkeypatch.setenv("TASKQUEUE_HOME", str(tmp_path / "b"))
    assert tq_home() == tmp_path / "a"
    monkeypatch.delenv("TQDAEMON_HOME")
    assert tq_home() == tmp_path / "b"


def test_missing_db_is_a_banner_not_an_error(tmp_path: Path) -> None:
    cfg = load_config(_project(tmp_path))
    _write_blueprints(cfg, [("translate", None)])
    data = queue_payload(cfg)
    assert data["ok"] and data["daemon"] == {"running": False, "db": False, "error": "queue database not found"}
    assert [t["task"] for t in data["tasks"]] == ["localize_ui_messages"]
    assert data["tasks"][0]["lane"] == "gpu" and data["tasks"][0]["vram"] > 0


def test_payload_reads_status_engine_and_vram_read_only(tmp_path: Path) -> None:
    cfg = load_config(_project(tmp_path))
    _write_blueprints(cfg, [("translate", None), ("sync", None), ("translate", "pl")])
    home = tmp_path / "tqhome"
    args = json.dumps(["run-translate", "demo", "--locales", "pl", "--engine", "claude-haiku"])
    _make_db(home, [
        ("demo", "localize_ui_messages", "queued", args, json.dumps({"gpu_vram_gib": 0.0}), "x.yaml", 7),
        ("other", "localize_sync", "running", "[]", "{}", "y.yaml", None),
    ])
    before = (home / "queue.db").read_bytes()
    data = queue_payload(cfg)
    assert (home / "queue.db").read_bytes() == before
    assert data["daemon"]["db"] is True and data["daemon"]["running"] is False
    by = {t["task"]: t for t in data["tasks"]}
    assert set(by) == {"localize_ui_messages", "localize_sync", "localize_ui_messages__pl"}
    main = by["localize_ui_messages"]
    assert main["status"] == "queued" and main["engine"] == "claude-haiku" and main["lane"] == "cloud"
    assert main["lastRun"]["status"] == "completed"
    # Another project's row never shows up.
    assert by["localize_sync"]["status"] == "not registered" and by["localize_sync"]["lane"] == "cpu"


def test_queue_engine_rewrites_only_existing_blueprints(tmp_path: Path) -> None:
    cfg = load_config(_project(tmp_path, CLOUD))
    out = _write_blueprints(cfg, [("translate", None), ("improve", None)])
    result = op_queue_engine(cfg, "claude-haiku")
    assert result.ok, result.summary
    assert sorted(p.name for p in out.iterdir()) == ["llm_localizator_improve.yaml", "llm_localizator_translate.yaml"]
    doc = pyyaml.safe_load((out / "llm_localizator_translate.yaml").read_text(encoding="utf-8"))
    assert "--engine" in doc["args"] and doc["args"][doc["args"].index("--engine") + 1] == "claude-haiku"
    assert "gpu_vram_gib" not in doc["resources"]
    row = result.data["rows"][0]
    assert row["before"]["lane"] == "gpu" and row["after"]["lane"] == "cloud"
    assert any("localize_ui_messages" in line for line in result.lines)
    # The project config is untouched.
    assert "[engine]" not in (tmp_path / ".llm-localize.toml").read_text(encoding="utf-8")


def test_queue_engine_dry_run_writes_nothing(tmp_path: Path) -> None:
    cfg = load_config(_project(tmp_path, CLOUD))
    out = _write_blueprints(cfg, [("translate", None)])
    path = out / "llm_localizator_translate.yaml"
    before = path.read_text(encoding="utf-8")
    result = op_queue_engine(cfg, "claude-haiku", dry_run=True)
    assert result.ok and result.data["written"] == [] and result.summary.startswith("dry run")
    assert path.read_text(encoding="utf-8") == before


def test_queue_engine_with_no_blueprints_creates_none(tmp_path: Path) -> None:
    cfg = load_config(_project(tmp_path, CLOUD))
    result = op_queue_engine(cfg, "claude-haiku")
    assert result.ok and not (tmp_path / "experiments").exists()
    assert blueprint_jobs(cfg) == []


def test_cloud_engine_without_allow_cloud_is_skipped_not_crashed(tmp_path: Path) -> None:
    """Without [privacy]/[budget] the job falls back to the GPU and the cloud model cannot be sized."""
    cfg = load_config(_project(tmp_path))
    out = _write_blueprints(cfg, [("improve", None)])
    before = (out / "llm_localizator_improve.yaml").read_text(encoding="utf-8")
    result = op_queue_engine(cfg, "claude-haiku")
    assert not result.ok and result.data["errors"]
    assert (out / "llm_localizator_improve.yaml").read_text(encoding="utf-8") == before


def test_unknown_engine_is_refused(tmp_path: Path) -> None:
    cfg = load_config(_project(tmp_path))
    assert op_queue_engine(cfg, "no-such-engine").exit_code == 2


def test_queue_route_is_registered() -> None:
    from llm_localizator.web.get_policy import policy_for_get
    from llm_localizator.web.shell import route_for_path

    assert policy_for_get("/api/queue") == "auth"
    assert route_for_path("/app/queue").id == "queue"
