"""Visual hunt: pseudo en-XX + Playwright crawl + static refresh (ADR-27 subprocess).

Dogfood (the engine's own UI) crawls with presets and intersects with the scan.
Any project with a ``[qa]`` block (ADR-119) gets the config-driven crawl instead:
leftovers, dynamic text and layout locales, reported under the engine data home.
The crawl script always comes from the engine's ``experiments/`` copy, never from
the consumer repo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..projects import ProjectConfig
from .agent_hardcoded import op_agent_hardcoded, scan_cache_status
from .source_ops import op_pseudo
from .types import AgentHardcodedRequest, OpResult, PseudoRequest

__all__ = ["op_hardcoded_hunt", "resolve_experiments_dir"]


def resolve_experiments_dir(cfg: ProjectConfig) -> Path | None:
    """Locate the engine's ``experiments/hardcoded_visible`` (or an explicit override).

    Never the consumer's own ``experiments/``: the hunt runs this code, and a
    project repo is not trusted to supply it.
    """
    override = (os.environ.get("LLM_LOCALIZE_EXPERIMENTS") or "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override) / "hardcoded_visible")
        candidates.append(Path(override))
    # Package install → walk up to a checkout that still has experiments/.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "experiments" / "hardcoded_visible")
    seen: set[str] = set()
    for path in candidates:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if (path / "crawl.py").is_file() and (path / "intersect.py").is_file():
            return path
    return None


def _run_script(script: Path, args: list[str], *, cwd: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(script), *args]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, f"timed out: {' '.join(cmd)}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def op_hardcoded_hunt(
    cfg: ProjectConfig,
    *,
    skip_crawl: bool = False,
    skip_static: bool = False,
    no_serve: bool = True,
) -> OpResult:
    """Pseudo en-XX, optional Playwright crawl/intersect, optional static refresh."""
    lines: list[str] = []
    data: dict = {"steps": []}
    qa = list(getattr(cfg, "qa_locales", None) or [])
    qa_cfg = getattr(cfg, "qa", None)
    if qa_cfg is not None:
        data["steps"].append({"step": "qa_locales", "ok": True, "detail": "[qa] config"})
    elif "en-XX" not in qa and "en-XA" not in qa:
        msg = (
            '[web] qa_locales does not include en-XX — add it and restart '
            "`llm-localizator web` before a visual hunt (ADR-110)."
        )
        lines.append(msg)
        data["steps"].append({"step": "qa_locales", "ok": False, "detail": msg})
        # Still allow pseudo + static for marker file / report refresh.
    else:
        data["steps"].append({"step": "qa_locales", "ok": True})

    pseudo = op_pseudo(cfg, PseudoRequest(locale="en-XX", style="xxxx"))
    lines.extend(pseudo.lines or [pseudo.summary])
    data["steps"].append({
        "step": "pseudo", "ok": pseudo.ok, "summary": pseudo.summary,
    })
    if not pseudo.ok:
        return OpResult(
            ok=False, exit_code=pseudo.exit_code, command="hardcoded-hunt",
            summary=pseudo.summary, lines=lines, data=data,
        )

    exp = resolve_experiments_dir(cfg)
    data["experiments"] = str(exp) if exp else None
    if skip_crawl:
        lines.append("crawl skipped (--skip-crawl)")
        data["steps"].append({"step": "crawl", "ok": True, "skipped": True})
    elif exp is None:
        msg = (
            "experiments/hardcoded_visible not found — dogfood checkout only. "
            "See experiments/hardcoded_visible/README.md (or set "
            "LLM_LOCALIZE_EXPERIMENTS)."
        )
        lines.append(msg)
        data["steps"].append({"step": "crawl", "ok": False, "detail": msg})
        return OpResult(
            ok=False, exit_code=1, command="hardcoded-hunt",
            summary=msg, lines=lines, data=data,
        )
    elif qa_cfg is not None:
        return _qa_crawl(cfg, exp, lines, data, no_serve=no_serve, skip_static=skip_static)
    else:
        crawl_args = ["--no-serve"] if no_serve else []
        code, out = _run_script(exp / "crawl.py", crawl_args, cwd=cfg.root)
        lines.append(out or f"crawl exit {code}")
        data["steps"].append({"step": "crawl", "ok": code == 0, "exit": code})
        if code != 0:
            hint = out or "crawl failed"
            if "playwright" in hint.lower() or code == 127:
                hint += " — install Playwright/Chromium for experiments (ADR-27)."
            return OpResult(
                ok=False, exit_code=code or 1, command="hardcoded-hunt",
                summary=hint, lines=lines, data=data,
            )
        code, out = _run_script(exp / "intersect.py", [], cwd=cfg.root)
        lines.append(out or f"intersect exit {code}")
        data["steps"].append({"step": "intersect", "ok": code == 0, "exit": code})
        if code != 0:
            return OpResult(
                ok=False, exit_code=code or 1, command="hardcoded-hunt",
                summary=out or "intersect failed", lines=lines, data=data,
            )
        leftovers = cfg.root / "reports" / "hardcoded_visible" / "leftovers.json"
        intersect = cfg.root / "reports" / "hardcoded_visible" / "intersect.md"
        data["leftovers"] = str(leftovers) if leftovers.is_file() else None
        data["intersect"] = str(intersect) if intersect.is_file() else None

    if not skip_static:
        static = op_agent_hardcoded(
            cfg,
            AgentHardcodedRequest(
                fmt="prompt",
                refresh=True,
                split="auto",
                out_dir=str(cfg.root / "reports" / "hardcoded"),
            ),
        )
        lines.append(static.summary)
        data["steps"].append({
            "step": "agent-hardcoded", "ok": static.ok, "summary": static.summary,
        })

    data["status"] = scan_cache_status(cfg)
    summary = "hardcoded-hunt finished — wire from leftovers (page+selector); re-pseudo after EN keys"
    lines.append(summary)
    return OpResult(
        ok=True, exit_code=0, command="hardcoded-hunt",
        summary=summary, lines=lines, data=data,
    )


def _qa_crawl(cfg: ProjectConfig, exp: Path, lines: list[str], data: dict, *,
              no_serve: bool, skip_static: bool) -> OpResult:
    """The ``[qa]``-driven crawl (ADR-119); reports go to the engine data home."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(cfg.data_root()) / "qa" / stamp
    target = (["--config", str(cfg.config_path)] if getattr(cfg, "config_path", None)
              else ["--project", cfg.name])
    args = [*target, "--out-dir", str(out_dir)] + (["--no-serve"] if no_serve else [])
    code, out = _run_script(exp / "crawl.py", args, cwd=exp)
    lines.append(out or f"crawl exit {code}")
    data["steps"].append({"step": "crawl", "ok": code == 0, "exit": code, "mode": "qa"})
    if code != 0:
        hint = out or "crawl failed"
        if "playwright" in hint.lower() or code == 127:
            hint += " — install Playwright/Chromium for experiments (ADR-27)."
        elif no_serve and "not reachable" in hint:
            hint += " — start the app, or pass --serve to run [qa] start."
        return OpResult(ok=False, exit_code=code or 1, command="hardcoded-hunt",
                        summary=hint, lines=lines, data=data)
    data["qa_report"] = str(out_dir)
    summary_file = out_dir / "summary.json"
    if summary_file.is_file():
        data["qa_summary"] = json.loads(summary_file.read_text(encoding="utf-8"))
    if not skip_static:
        static = op_agent_hardcoded(cfg, AgentHardcodedRequest(
            fmt="prompt", refresh=True, split="auto",
            out_dir=str(Path(cfg.data_root()) / "reports" / "hardcoded"),
        ))
        lines.append(static.summary)
        data["steps"].append({"step": "agent-hardcoded", "ok": static.ok, "summary": static.summary})
    data["status"] = scan_cache_status(cfg)
    summary = f"hardcoded-hunt finished — QA report in {out_dir} (index.md, dynamic_text.json)"
    lines.append(summary)
    return OpResult(ok=True, exit_code=0, command="hardcoded-hunt",
                    summary=summary, lines=lines, data=data)
