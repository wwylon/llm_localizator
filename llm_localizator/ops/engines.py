"""Engine operations (ADR-156): list, show, recommend and apply a whole-pipeline engine.

``apply`` writes ``[engine] id`` and removes the project keys that would hide the engine's settings; per-locale
overrides (``[locales.models] de = …``, ``[locales.providers]``) stay. It never touches ``[privacy]`` or ``[budget]``:
for a cloud engine it prints the lines the user still has to add. Unbenchmarked engines need ``accept_unbenchmarked``
(ADR-12: a model swap needs evidence).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..engines import Engine, EngineError, all_engines, get_engine, shadowing_keys
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["detect_vram_gib", "keys_present", "recommend_engine", "op_engine"]

#: Recommendation order: evidence first, then cost (cloud cheapest per sweep, then local by size).
_PREFERENCE = ("claude-haiku", "deepseek", "local-8gb", "local-4gb", "openai", "local-16gb", "hybrid-local-haiku")


def detect_vram_gib() -> float | None:
    """Total VRAM of the largest NVIDIA GPU via ``nvidia-smi``; None when unknown. Best effort, 5 s."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    sizes = [float(x) for x in out.stdout.split() if x.replace(".", "", 1).isdigit()]
    return round(max(sizes) / 1024, 1) if sizes else None


def keys_present() -> dict[str, bool]:
    """Which cloud API keys are set (yes/no only; values are never read out)."""
    names = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")
    return {name: bool((os.environ.get(name) or "").strip()) for name in names}


def _fits(engine: Engine, vram: float | None, keys: dict[str, bool]) -> tuple[bool, str]:
    if engine.api_key_env and not keys.get(engine.api_key_env):
        return False, f"needs {engine.api_key_env}"
    if engine.vram_gib and (vram is None or vram < engine.vram_gib):
        have = "no GPU found" if vram is None else f"{vram:g} GB found"
        return False, f"needs {engine.vram_gib:g} GB VRAM ({have})"
    return True, "ready"


def recommend_engine(vram: float | None, keys: dict[str, bool], *, gpu_busy: bool = False) -> tuple[str | None, str]:
    """First engine in preference order whose requirements are met. ``gpu_busy`` skips GPU engines."""
    engines = all_engines()
    for engine_id in _PREFERENCE:
        engine = engines.get(engine_id)
        if engine is None or (gpu_busy and engine.vram_gib):
            continue
        ok, _why = _fits(engine, vram, keys)
        if ok:
            reason = "cloud key present" if engine.cloud else f"{vram:g} GB GPU"
            return engine_id, reason
    return None, "no API key and no GPU found: set ANTHROPIC_API_KEY (cheapest) or install Ollama on a GPU"


def _cloud_lines(cfg: ProjectConfig, engine: Engine) -> list[str]:
    if not engine.cloud:
        return []
    missing = []
    if not getattr(cfg, "allow_cloud", False):
        missing.append("[privacy]\nallow_cloud = true")
    if float(getattr(cfg, "budget_monthly_usd", 0) or 0) <= 0:
        missing.append("[budget]\nmonthly_usd = 5   # your cap\nmode = \"dynamic\"")
    if not missing:
        return []
    return ["This engine sends text to a cloud API. Add to .llm-localize.toml yourself (not written for you):",
            *missing]


def _apply(cfg: ProjectConfig, engine: Engine) -> tuple[str | None, list[str]]:
    import tomllib

    import tomlkit

    from ..catalog.mutation_lock import project_mutation_lock
    from ..web.config_write import write_config_atomically

    path = Path(cfg.config_path)
    text = path.read_text(encoding="utf-8")
    shadows = shadowing_keys(tomllib.loads(text), engine)
    doc = tomlkit.parse(text)
    removed = []
    for section, key, value in shadows:
        table = doc
        for part in section.split("."):
            table = table[part]
        del table[key]
        removed.append(f"removed [{section}] {key} = {value!r} (the engine sets it)")
    if "engine" not in doc:
        doc["engine"] = tomlkit.table()
    doc["engine"]["id"] = engine.id
    with project_mutation_lock(cfg):
        error = write_config_atomically(path, tomlkit.dumps(doc))
    return error, removed


def _fetch(url: str | None, *, write: bool, accept_unverified: bool) -> OpResult:
    from ..engines.fetch import fetch_engines

    try:
        rows = fetch_engines(url, write=write, accept_unverified=accept_unverified)
    except EngineError as exc:
        return OpResult(ok=False, exit_code=1, command="engine", summary=f"engine fetch failed: {exc}")
    lines = []
    for r in rows:
        trust = "verified" if r.verified else "UNVERIFIED"
        done = " -> written" if r.written else ""
        lines.append(f"  {r.id:<22} {r.status:<9} {trust}{done}" + (f"  ({r.detail})" if r.detail else ""))
    pending = [r for r in rows if r.status in ("new", "updated") and not r.written]
    if pending and not write:
        lines.append("Dry run: pass --write to save new or updated engines to ~/.llm_localize/engines/.")
    elif any(not r.verified for r in pending):
        lines.append("Unverified engines were not written: read them, then pass --accept-unverified.")
    rejected = [r for r in rows if r.status == "rejected"]
    summary = f"{len(rows)} engine(s) listed, {sum(r.written for r in rows)} written, {len(rejected)} rejected"
    return OpResult(ok=not rejected, exit_code=0 if not rejected else 1, command="engine", summary=summary,
                    lines=lines, data={"fetched": [r.__dict__ for r in rows]})


def op_engine(
    cfg: ProjectConfig, action: str = "list", engine_id: str | None = None, *,
    accept_unbenchmarked: bool = False, vram: float | None = None, gpu_busy: bool = False,
    url: str | None = None, write: bool = False, accept_unverified: bool = False,
) -> OpResult:
    """``list`` | ``show`` | ``recommend`` | ``apply`` (alias ``use``) | ``fetch``."""
    if action == "use":
        action = "apply"
    if action == "fetch":
        return _fetch(url, write=write, accept_unverified=accept_unverified)
    keys = keys_present()
    vram_found = vram if vram is not None else detect_vram_gib()
    current = getattr(cfg, "engine_id", None)
    rec, reason = recommend_engine(vram_found, keys, gpu_busy=gpu_busy)
    engines = all_engines()
    rows = []
    for engine in engines.values():
        ok, why = _fits(engine, vram_found, keys)
        rows.append({**engine.as_dict(), "fits": ok, "why": why, "current": engine.id == current,
                     "recommended": engine.id == rec})
    data = {"engines": rows, "current": current, "recommended": rec, "reason": reason,
            "vramGib": vram_found, "keys": keys}

    if action in ("list", "recommend"):
        lines = []
        for row in rows:
            mark = "*" if row["current"] else ("+" if row["recommended"] else " ")
            lines.append(f"{mark} {row['id']:<20} [{row['status']}] {row['name']}: {row['why']}")
            if row["summary"]:
                lines.append(f"    {row['summary']}")
        lines.append(f"Recommended here: {rec or 'none'} ({reason}).")
        summary = f"engine {current}" if current else f"no engine set; recommended: {rec or 'none'}"
        if action == "recommend":
            summary = f"recommended engine: {rec or 'none'} ({reason})"
        return OpResult(ok=True, exit_code=0, command="engine", summary=summary, lines=lines, data=data)

    if not engine_id:
        return OpResult(ok=False, exit_code=2, command="engine", summary=f"engine {action} needs an engine id")
    try:
        engine = get_engine(engine_id)
    except EngineError as exc:
        return OpResult(ok=False, exit_code=2, command="engine", summary=str(exc), data=data)
    lines = [f"{engine.id}: {engine.name} [{engine.status}]", f"  {engine.summary}"]
    if engine.evidence:
        lines.append(f"  evidence: {engine.evidence}")
    lines += [f"  [{section}] {key} = {value!r}" for section, key, value in engine.settings()]
    data["engine"] = engine.as_dict()
    if action == "show":
        return OpResult(ok=True, exit_code=0, command="engine", summary=f"engine {engine.id}", lines=lines, data=data)
    if action != "apply":
        return OpResult(ok=False, exit_code=2, command="engine", summary=f"unknown engine action {action!r}")

    if engine.status == "unbenchmarked" and not accept_unbenchmarked:
        return OpResult(ok=False, exit_code=3, command="engine", lines=lines, data=data, summary=(
            f"{engine.id} has no benchmark evidence (ADR-12). Run a bakeoff first, or pass "
            "--accept-unbenchmarked to switch anyway"))
    if not getattr(cfg, "config_path", None):
        return OpResult(ok=False, exit_code=2, command="engine", summary="this project has no config file to write")
    error, removed = _apply(cfg, engine)
    if error:
        return OpResult(ok=False, exit_code=1, command="engine", summary=f"config not written: {error}", data=data)
    lines += ["", f"wrote [engine] id = \"{engine.id}\" to {cfg.config_path}", *removed, *_cloud_lines(cfg, engine)]
    if engine.cloud is False or not _cloud_lines(cfg, engine):
        lines.append("Queue blueprints: run `llm-localizator init <project> --taskqueue` to regenerate them for this engine.")
    return OpResult(ok=True, exit_code=0, command="engine", summary=f"engine set to {engine.id}", lines=lines,
                    data={**data, "current": engine.id, "removed": removed})
