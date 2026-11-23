"""Verification run: disposable workspace, stage loop, resumable run record.

A run copies the target project, drives the engine against the copy and writes
``<out>/runs/<id>/run.json`` plus a ``VERIFY.md`` summary. The user's checkout is
never written. The copy is checked after every stage: the engine may write only
catalogue files and its own state (ADR-32).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..projects.config import CONFIG_FILENAME

__all__ = [
    "PROFILES", "StageResult", "Ctx", "run_verify", "render_markdown", "exit_code_for",
]

PASS, DEGRADED, FAIL = "pass", "degraded", "fail"
UNSUPPORTED, SKIPPED, PENDING, RUNNING = "unsupported", "skipped", "pending", "running"

#: Worst first. ``skipped`` and ``pending`` never raise the exit code.
_SEVERITY = {FAIL: 3, DEGRADED: 2, UNSUPPORTED: 1, PASS: 0, SKIPPED: 0, PENDING: 0, RUNNING: 0}

#: Directories never copied into the workspace or snapshotted.
_COPY_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", ".turbo"}

PROFILES: dict[str, tuple[str, ...]] = {
    "quick": ("S0", "S1", "S2", "S3", "S4", "S8"),
    "standard": ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S8"),
    "deep": ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"),
}


@dataclass
class StageResult:
    stage: str
    title: str
    verdict: str = PENDING
    notes: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    seconds: float = 0.0

    def worsen(self, verdict: str, note: str = "") -> None:
        """Raise the verdict to *verdict* if it is worse than the current one."""
        if _SEVERITY[verdict] > _SEVERITY.get(self.verdict, 0) or self.verdict in (PENDING, RUNNING):
            self.verdict = verdict
        if note:
            self.notes.append(note)


class Ctx:
    """Everything a stage needs; stages mutate it to hand facts to later stages."""

    def __init__(self, src: Path, ws: Path, run_dir: Path, profile: str, locales: str | None):
        self.src = src
        self.ws = ws
        self.run_dir = run_dir
        self.profile = profile
        self.locales = locales
        self.cfg = None  # ProjectConfig, set by S1
        self.fingerprint: dict = {}
        self.has_catalogue = False
        self.scan_configured_by_verify = False
        self.violations: list[dict] = []
        self._baseline: dict[str, tuple[int, int]] = {}

    # -- source-safety snapshot ------------------------------------------------

    def snapshot(self) -> None:
        self._baseline = _stat_tree(self.ws)

    def allowed(self, rel: str) -> bool:
        """True for paths the engine is permitted to write."""
        parts = rel.split("/")
        if any(p.startswith(".llm-") or p == ".llm-localizator" for p in parts):
            return True
        if parts[-1] == CONFIG_FILENAME:
            return True
        cfg = self.cfg
        if cfg is None:
            return False
        state = getattr(cfg, "state_dir", None)
        if state:
            try:
                srel = Path(state).resolve().relative_to(self.ws.resolve()).as_posix()
                if rel == srel or rel.startswith(srel + "/"):
                    return True
            except (ValueError, OSError):
                pass
        template = getattr(cfg, "catalog_path", None)
        if template:
            return _template_regex(template).fullmatch(rel) is not None
        return False

    def check_writes(self, stage: str) -> list[str]:
        """Record writes outside the allowed set; return their relative paths."""
        bad: list[str] = []
        now = _stat_tree(self.ws)
        for rel, sig in now.items():
            if self._baseline.get(rel) == sig:
                continue
            if self.allowed(rel):
                self._baseline[rel] = sig
                continue
            orig = self.src / rel
            if rel in self._baseline and orig.is_file() and _same_bytes(orig, self.ws / rel):
                self._baseline[rel] = sig  # touched, content unchanged
                continue
            bad.append(rel)
            self._baseline[rel] = sig
        for rel in set(self._baseline) - set(now):
            if not self.allowed(rel):
                bad.append(rel)
            self._baseline.pop(rel, None)
        if bad:
            self.violations.append({"stage": stage, "paths": sorted(bad)})
        return bad


Stage = Callable[[Ctx], StageResult]


def _template_regex(template: str) -> re.Pattern:
    out = ""
    for piece in re.split(r"(\{[a-z_]+\})", template.replace("\\", "/")):
        if piece in ("{locale}", "{namespace}"):
            out += r"[^/]+" if piece == "{locale}" else r".+"
        elif piece.startswith("{") and piece.endswith("}"):
            out += r"[^/]+"
        else:
            out += re.escape(piece)
    return re.compile(out)


def _stat_tree(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _COPY_SKIP]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except OSError:
                continue
            out[path.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def exit_code_for(results: list[StageResult]) -> int:
    worst = max((_SEVERITY[r.verdict] for r in results), default=0)
    return {3: 1, 2: 2, 1: 2}.get(worst, 0)


def _registry() -> dict[str, tuple[str, Stage]]:
    from . import stages

    return stages.STAGES


def run_verify(
    src: Path,
    *,
    profile: str = "quick",
    out: Path | None = None,
    resume: str | None = None,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    locales: str | None = None,
    stages_override: dict[str, tuple[str, Stage]] | None = None,
) -> tuple[Path, list[StageResult]]:
    """Run the profile's stages on a copy of *src*. Returns (run dir, results)."""
    src = Path(src).resolve()
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose from {', '.join(PROFILES)}")
    if not src.is_dir():
        raise ValueError(f"not a directory: {src}")
    base = Path(out) if out else Path(os.environ.get("TEMP", "/tmp")) / "llm-localizator-verify" / src.name
    runs = base / "runs"
    run_id = resume or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = runs / run_id
    ws = run_dir / "ws"
    registry = stages_override or _registry()

    prior: dict[str, StageResult] = {}
    fingerprint: dict = {}
    if resume:
        if not (run_dir / "run.json").is_file():
            raise ValueError(f"no run {resume!r} under {runs}")
        record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        profile = record.get("profile", profile)
        fingerprint = record.get("fingerprint", {})
        for item in record.get("stages", []):
            prior[item["stage"]] = StageResult(**item)
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            src, ws, symlinks=True, ignore=shutil.ignore_patterns(*_COPY_SKIP),
        )

    ctx = Ctx(src, ws, run_dir, profile, locales)
    ctx.fingerprint = fingerprint
    cfg_file = ws / CONFIG_FILENAME
    if resume and cfg_file.is_file():
        from ..projects import load_config

        ctx.cfg = load_config(cfg_file)
        ctx.has_catalogue = bool(fingerprint.get("has_catalogue"))
    ctx.snapshot()

    wanted = [s for s in PROFILES[profile] if (not only or s in only) and s not in (skip or [])]
    results: list[StageResult] = []
    home = run_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    saved_env = os.environ.get("LLM_LOCALIZE_HOME")
    os.environ["LLM_LOCALIZE_HOME"] = str(home)  # never touch the real registry
    try:
        for sid in wanted:
            old = prior.get(sid)
            if old and old.verdict not in (PENDING, RUNNING):
                results.append(old)
                continue
            title, fn = registry.get(sid, (sid, None))
            started = time.perf_counter()
            if fn is None:
                res = StageResult(sid, title, SKIPPED, ["not implemented yet"])
            else:
                try:
                    res = fn(ctx)
                except Exception as exc:  # a crash is a FAIL, never an abort of the run
                    res = StageResult(sid, title, FAIL, [
                        f"crashed: {type(exc).__name__}: {exc}",
                        traceback.format_exc(limit=6),
                    ])
            res.seconds = round(time.perf_counter() - started, 3)
            bad = ctx.check_writes(sid) if sid != "S8" else []
            if bad:
                res.worsen(FAIL, f"wrote outside catalogue/state: {', '.join(bad[:5])}")
            results.append(res)
            _save(run_dir, src, profile, ctx, results)
    finally:
        if saved_env is None:
            os.environ.pop("LLM_LOCALIZE_HOME", None)
        else:
            os.environ["LLM_LOCALIZE_HOME"] = saved_env
    _save(run_dir, src, profile, ctx, results)
    (run_dir / "VERIFY.md").write_text(render_markdown(src, profile, ctx, results), encoding="utf-8")
    return run_dir, results


def _save(run_dir: Path, src: Path, profile: str, ctx: Ctx, results: list[StageResult]) -> None:
    record = {
        "source": str(src),
        "profile": profile,
        "fingerprint": {**ctx.fingerprint, "has_catalogue": ctx.has_catalogue},
        "violations": ctx.violations,
        "stages": [asdict(r) for r in results],
    }
    (run_dir / "run.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def render_markdown(src: Path, profile: str, ctx: Ctx, results: list[StageResult]) -> str:
    fp = ctx.fingerprint
    lines = [
        f"# Verify: {src.name}",
        "",
        f"Profile `{profile}` - source `{src}`",
        "",
    ]
    if fp:
        lines += [
            f"Size tier **{fp.get('tier', '?')}** ({fp.get('files', '?')} files, "
            f"{fp.get('lines', '?')} lines) - maturity **{fp.get('maturity', '?')}**",
            f"i18n libraries: {', '.join(fp.get('i18n_libs', [])) or 'none detected'}",
            "",
        ]
    lines += ["| Stage | Verdict | Seconds | Notes |", "|---|---|---|---|"]
    for r in results:
        note = "; ".join(n.splitlines()[0] for n in r.notes if n)[:300].replace("|", "/")
        lines.append(f"| {r.stage} {r.title} | **{r.verdict}** | {r.seconds} | {note} |")
    lines.append("")
    for r in results:
        if r.metrics:
            lines.append(f"## {r.stage} {r.title} metrics")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(r.metrics, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")
    if ctx.violations:
        lines += ["## Source-safety violations", ""]
        for v in ctx.violations:
            lines.append(f"- after {v['stage']}: {', '.join(v['paths'][:10])}")
        lines.append("")
    return "\n".join(lines)
