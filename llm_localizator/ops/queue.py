"""Queue view and engine switch for the project's taskqueue blueprints (W3).

``queue_payload`` is read-only: it lists the blueprint files under ``experiments/operator_queue`` that run
llm-localizator and joins each with its row in the taskqueue SQLite DB, opened with ``mode=ro`` (the daemon owns
that file; the web UI never writes it and never starts the daemon).

``op_queue_engine`` rewrites only blueprints that already exist, with ``--engine <id>`` baked into ``args`` and
the reservation sized for that engine. It never creates a blueprint: a new YAML may be picked up and run at once.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["tq_home", "daemon_running", "blueprint_jobs", "job_row", "queue_payload", "op_queue_engine"]

_JOBS = ("translate", "sync", "improve", "review", "documents", "rescore")


def tq_home() -> Path:
    """$TQDAEMON_HOME, then $TASKQUEUE_HOME, then ~/.tqdaemon."""
    for name in ("TQDAEMON_HOME", "TASKQUEUE_HOME"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return Path(value)
    return Path.home() / ".tqdaemon"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # signal 0: existence check only (POSIX)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def daemon_running(home: Path) -> bool:
    """True when ``daemon.pid`` names a live process. A missing or unreadable pid file means down."""
    try:
        pid = int((home / "daemon.pid").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return False
    return _pid_alive(pid)


def blueprint_jobs(cfg: ProjectConfig) -> list[tuple[str, str | None, Path]]:
    """``(job, locale, path)`` for every llm-localizator blueprint file that exists for this project."""
    from ..projects.taskqueue import blueprint_filename

    out_dir = cfg.root / "experiments" / "operator_queue"
    found: list[tuple[str, str | None, Path]] = []
    for job in _JOBS:
        path = out_dir / blueprint_filename(job)
        if path.is_file():
            found.append((job, None, path))
    for loc in cfg.targets:
        path = out_dir / blueprint_filename("translate", loc)
        if path.is_file():
            found.append(("translate", loc, path))
    return found


def job_row(cfg: ProjectConfig, job: str, locale: str | None = None) -> dict:
    """Task id, pinned model, VRAM reservation and lane, computed the way ``generate_blueprint`` does."""
    from ..projects.taskqueue import _job_models, _pinned_model, derive_vram, job_runs_on_cloud, task_id_for

    row: dict = {"task": task_id_for(job, locale), "job": job, "locale": locale, "engine": cfg_engine(cfg)}
    if job == "sync":
        return {**row, "model": "", "vram": 0.0, "lane": "cpu"}
    try:
        cloud = job_runs_on_cloud(cfg, job, locale)
    except Exception as exc:  # noqa: BLE001 -- a bad config shows in the table, not as a 500
        return {**row, "model": "", "vram": None, "lane": "?", "error": str(exc)}
    if cloud:
        model = cfg.model_for(locale or (cfg.active_targets() or [""])[0]) if job == "translate" else (
            _pinned_model(cfg, job, locale))
        return {**row, "model": model, "vram": 0.0, "lane": "cloud"}
    pin = _pinned_model(cfg, job, locale)
    try:
        vram = derive_vram(_job_models(cfg, job, pin))
    except ValueError as exc:
        return {**row, "model": pin, "vram": None, "lane": "gpu", "error": str(exc)}
    return {**row, "model": pin, "vram": vram, "lane": "gpu"}


def cfg_engine(cfg: ProjectConfig) -> str:
    return str(getattr(cfg, "engine_id", None) or "")


def _arg_value(args: list, flag: str) -> str:
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return str(args[i + 1])
    return ""


def _read_db(home: Path, project: str) -> tuple[dict[str, dict], str | None]:
    """Task rows for *project* keyed by task id, from the DB opened read-only. Error text instead of raising."""
    db = home / "queue.db"
    if not db.is_file():
        return {}, "queue database not found"
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    except sqlite3.Error as exc:
        return {}, f"queue database unreadable: {exc}"
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT t.task_id, t.status, t.args, t.resources, t.yaml_source, t.last_run_id, "
            "r.status AS run_status, r.finished_at, r.last_log_line "
            "FROM tasks t LEFT JOIN runs r ON r.run_id = t.last_run_id WHERE t.project = ?",
            (project,),
        ).fetchall()
    except sqlite3.Error as exc:
        return {}, f"queue database unreadable: {exc}"
    finally:
        conn.close()
    out: dict[str, dict] = {}
    for row in rows:
        out[row["task_id"]] = dict(row)
    return out, None


def _loads(raw, default):
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def queue_payload(cfg: ProjectConfig, *, home: Path | None = None) -> dict:
    """Blueprint tasks of *cfg* with their queue status. Never writes anything."""
    home = home or tq_home()
    up = daemon_running(home)
    db_rows, db_error = _read_db(home, cfg.name)
    tasks = []
    for job, locale, path in blueprint_jobs(cfg):
        row = job_row(cfg, job, locale)
        db = db_rows.get(row["task"])
        args = _loads(db.get("args"), []) if db else []
        resources = _loads(db.get("resources"), {}) if db else {}
        engine = _arg_value(args, "--engine") or row["engine"]
        model = _arg_value(args, "--model") or row["model"]
        vram = resources.get("gpu_vram_gib") if db and "gpu_vram_gib" in resources else row["vram"]
        lane = row["lane"]
        if db and job != "sync":
            lane = "gpu" if float(vram or 0) > 0 else "cloud"
        tasks.append({
            "task": row["task"], "job": job, "locale": locale, "file": path.name,
            "status": (db or {}).get("status") or ("not registered" if not db_error else "unknown"),
            "lastRun": {"status": db.get("run_status"), "finishedAt": db.get("finished_at"),
                        "lastLine": db.get("last_log_line")} if db and db.get("last_run_id") else None,
            "engine": engine, "model": model, "vram": vram, "lane": lane,
            "error": row.get("error"),
        })
    return {
        "ok": True, "project": cfg.name, "engine": cfg_engine(cfg),
        "daemon": {"running": up, "db": db_error is None, "error": db_error},
        "tasks": tasks,
    }


def op_queue_engine(cfg: ProjectConfig, engine_id: str, *, dry_run: bool = False) -> OpResult:
    """Rewrite this project's existing blueprints for *engine_id*; print a before/after table."""
    from ..catalog.io import atomic_write_text
    from ..engines import EngineError, get_engine
    from ..projects.config import ConfigError, load_config
    from ..projects.taskqueue import generate_blueprint

    if not engine_id:
        return OpResult(ok=False, exit_code=2, command="queue-engine", summary="queue-engine needs an engine id")
    try:
        get_engine(engine_id)
    except EngineError as exc:
        return OpResult(ok=False, exit_code=2, command="queue-engine", summary=str(exc))
    if not getattr(cfg, "config_path", None):
        return OpResult(ok=False, exit_code=2, command="queue-engine", summary="this project has no config file")
    try:
        after_cfg = load_config(cfg.config_path, engine_override=engine_id)
    except ConfigError as exc:
        return OpResult(ok=False, exit_code=2, command="queue-engine", summary=str(exc))

    jobs = blueprint_jobs(cfg)
    if not jobs:
        return OpResult(ok=True, exit_code=0, command="queue-engine", data={"rows": [], "written": []},
                        summary="no blueprints to update (none exist; this command never creates one)")
    rows, written, errors = [], [], []
    for job, locale, path in jobs:
        before = job_row(cfg, job, locale)
        after = job_row(after_cfg, job, locale)
        after["engine"] = engine_id
        rows.append({"task": before["task"], "file": path.name, "before": before, "after": after})
        if after.get("error"):
            errors.append(f"{path.name}: {after['error']}")
            continue
        if dry_run:
            continue
        try:
            text = generate_blueprint(after_cfg, job, locale=locale, extra_args={"--engine": engine_id})
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        atomic_write_text(path, text)
        written.append(path.name)

    def fmt(r: dict) -> str:
        vram = "?" if r.get("vram") is None else f"{r['vram']:g} GiB"
        return f"{r.get('model') or '-'} / {vram} / {r.get('lane')}"

    lines = [f"{'task':<36} {'before (model / VRAM / lane)':<40} after"]
    lines += [f"{r['task']:<36} {fmt(r['before']):<40} {fmt(r['after'])}" for r in rows]
    lines += [f"skipped {e}" for e in errors]
    if dry_run:
        summary = f"dry run: {len(rows) - len(errors)} blueprint(s) would use engine {engine_id}"
    else:
        summary = f"{len(written)} blueprint(s) now use engine {engine_id}"
    return OpResult(ok=not errors, exit_code=0 if not errors else 1, command="queue-engine", summary=summary,
                    lines=lines, data={"rows": rows, "written": written, "errors": errors, "dryRun": dry_run})
