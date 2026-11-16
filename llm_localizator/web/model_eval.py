"""Model-eval page helpers — bakeoff reports only; never edit [locales.models]."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..catalog.io import atomic_write_text
from ..catalog.state import now_iso
from ..pipeline.bakeoff_report import has_winner as _has_winner
from ..pipeline.bakeoff_report import parse_winners as _parse_winners
from ..projects.config import ProjectConfig
from ..projects.taskqueue import locale_task_suffix, tq_available

__all__ = [
    "bakeoff_root",
    "model_eval_view",
    "run_bakeoff",
    "run_eval",
    "report_text",
    "apply_recommendation",
]

LIMIT_MIN, LIMIT_MAX, LIMIT_DEFAULT = 10, 500, 50
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,119}$")
_APPLY_NOTES = "apply-notes.md"
def bakeoff_root() -> Path | None:
    """Engine checkout ``experiments/quality_bakeoff`` when present."""
    candidate = Path(__file__).resolve().parents[2] / "experiments" / "quality_bakeoff"
    return candidate if candidate.is_dir() else None


def operator_queue_root() -> Path | None:
    root = bakeoff_root()
    if root is None:
        return None
    queue = root.parent / "operator_queue"
    return queue if queue.is_dir() else None


def _tq_base() -> list[str] | None:
    for name in ("tq", "taskqueue"):
        if shutil.which(name):
            return [name]
    return None


def _report_path(root: Path, report: str) -> Path | str:
    """A report file under ``root``, or an error message. Names only; no path parts."""
    raw = str(report or "")
    name = Path(raw).name
    if not name or "/" in raw or "\\" in raw or ".." in name or not name.endswith(".md"):
        return "invalid report name"
    path = root / name
    if not path.is_file():
        return f"report not found: {name}"
    return path


def _setup_hints(cfg: ProjectConfig | None) -> dict[str, Any]:
    """Defaults for the setup form: active locales, pinned candidates, limit bounds."""
    from ..pipeline.bakeoff_ledger import PINNED_MODELS

    return {
        "locales": list(cfg.active_targets()) if cfg is not None else [],
        "pinned": list(PINNED_MODELS),
        "limit": {"min": LIMIT_MIN, "max": LIMIT_MAX, "default": LIMIT_DEFAULT},
    }


def report_text(name: str) -> dict[str, Any]:
    """Body of one bakeoff markdown report, for the history View panel."""
    root = bakeoff_root()
    if root is None:
        return {"ok": False, "error": "bakeoff directory not found"}
    path = _report_path(root, name)
    if isinstance(path, str):
        return {"ok": False, "error": path}
    return {"ok": True, "name": path.name, "text": path.read_text(encoding="utf-8")}


def model_eval_view(cfg: ProjectConfig | None = None) -> dict[str, Any]:
    root = bakeoff_root()
    hints = _setup_hints(cfg)
    if root is None:
        return {
            **hints,
            "ok": True,
            "available": False,
            "error": (
                "Bakeoff reports live under experiments/quality_bakeoff "
                "in the llm_localizator engine checkout."
            ),
            "reports": [],
            "comparison": [],
            "has_winner": False,
            "calibrate": {
                "script": "experiments/quality_bakeoff/calibrate_gold.py",
                "docs": "docs/model-evaluation.md",
            },
        }
    reports: list[dict[str, Any]] = []
    comparison: list[dict[str, str]] = []
    has_winner = False
    for path in sorted(root.glob("*.md")):
        if path.name == _APPLY_NOTES:
            continue
        text = path.read_text(encoding="utf-8")
        winner = _has_winner(text)
        if winner:
            has_winner = True
        entry = {
            "name": path.name,
            "mtime": datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc,
            ).isoformat().replace("+00:00", "Z"),
            "has_winner": winner,
            "size": path.stat().st_size,
        }
        reports.append(entry)
        if path.name == "REPORT.md" and winner:
            comparison = _parse_winners(text)
    return {
        **hints,
        "ok": True,
        "available": True,
        "reports": reports,
        "comparison": comparison,
        "has_winner": has_winner,
        "calibrate": {
            "script": "experiments/quality_bakeoff/calibrate_gold.py",
            "docs": "docs/model-evaluation.md",
        },
    }


def run_bakeoff(*, locale: str = "pl") -> dict[str, Any]:
    """Enqueue the existing matrix YAML via taskqueue. Never run bakeoff in-process."""
    if not tq_available():
        return {
            "ok": False,
            "error": (
                "tq is not on PATH. Bakeoff will not start a background shell "
                "(ADR-28). Install taskqueue or run "
                "experiments/quality_bakeoff/run_bakeoff.py from a terminal."
            ),
        }
    queue = operator_queue_root()
    if queue is None:
        return {"ok": False, "error": "operator_queue directory not found next to quality_bakeoff"}
    suffix = locale_task_suffix(locale.strip() or "pl")
    yaml_path = queue / f"quality_bakeoff_matrix_{suffix}.yaml"
    if not yaml_path.is_file():
        return {"ok": False, "error": f"no bakeoff blueprint for locale {locale!r}: {yaml_path.name}"}
    base = _tq_base()
    if base is None:
        return {
            "ok": False,
            "error": (
                "tq is not on PATH. Bakeoff will not start a background shell "
                "(ADR-28)."
            ),
        }
    add = subprocess.run(
        [*base, "add", str(yaml_path), "--project", "llm_localizator"],
        capture_output=True, text=True, timeout=60,
    )
    task = f"llm_localizator/quality_bakeoff_matrix_{suffix}"
    retry = subprocess.run(
        [*base, "retry", task],
        capture_output=True, text=True, timeout=60,
    )
    ok = add.returncode == 0  # retry only re-arms an existing task; add decides success
    msg = (retry.stdout or retry.stderr or add.stdout or add.stderr or "").strip()
    if not ok:
        return {"ok": False, "error": msg or f"tq failed for {task}"}
    return {"ok": True, "task": task, "message": msg or f"queued {task}"}


def run_eval(
    cfg: ProjectConfig,
    *,
    locale: str,
    model: str = "",
    limit: Any = None,
    corpus: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Single-model run or dry run through ``op_bakeoff``.

    A real run is always submitted to taskqueue (ADR-28): never inline in the web
    process. A dry run only counts cells and keys.
    """
    from ..ops.bakeoff import op_bakeoff
    from ..ops.types import BakeoffRequest

    locale = (locale or "").strip()
    if locale not in cfg.active_targets():
        return {"ok": False, "error": f"locale {locale!r} is not an active target"}
    model = (model or "").strip()
    if model and not _MODEL_RE.match(model):
        return {"ok": False, "error": "invalid model name"}
    try:
        size = int(limit) if limit not in (None, "") else LIMIT_DEFAULT
    except (TypeError, ValueError):
        return {"ok": False, "error": "sample size must be a number"}
    if not LIMIT_MIN <= size <= LIMIT_MAX:
        return {"ok": False, "error": f"sample size must be {LIMIT_MIN}-{LIMIT_MAX}"}
    if corpus not in ("", "builtin"):
        return {"ok": False, "error": "test set must be the project sample or builtin"}
    result = op_bakeoff(cfg, BakeoffRequest(
        locales=[locale],
        models=[model] if model else None,
        limit=size,
        corpus=corpus or None,
        dry_run=dry_run,
        submit=not dry_run,
    ))
    return {
        "ok": result.ok,
        "message": result.summary,
        "lines": list(result.lines),
        "data": result.data,
        **({} if result.ok else {"error": result.summary}),
    }


def apply_recommendation(
    cfg: ProjectConfig,
    *,
    report: str,
) -> dict[str, Any]:
    """Append a dated note. Does not edit consumer config or [locales.models]."""
    root = bakeoff_root()
    if root is None:
        return {"ok": False, "error": "bakeoff directory not found"}
    path = _report_path(root, report)
    if isinstance(path, str):
        return {"ok": False, "error": path}
    name = path.name
    if name == _APPLY_NOTES:
        return {"ok": False, "error": "cannot apply the apply-notes file"}
    text = path.read_text(encoding="utf-8")
    if not _has_winner(text):
        return {"ok": False, "error": "Winner note missing; apply is disabled"}
    notes = root / _APPLY_NOTES
    block = (
        f"\n## Applied {now_iso()}\n\n"
        f"- report: `{name}`\n"
        f"- project: `{cfg.name}`\n"
        f"- note: operator acknowledged the Winner table; "
        f"`[locales.models]` was not edited (ADR-12).\n"
    )
    prior = notes.read_text(encoding="utf-8") if notes.exists() else (
        "# Bakeoff apply notes\n\n"
        "Dated acknowledgements from the model-eval page. "
        "These do not change consumer config.\n"
    )
    atomic_write_text(notes, prior.rstrip() + "\n" + block)
    return {"ok": True, "notes": str(notes)}
