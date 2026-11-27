"""Ad hoc quality report (C-016, ADR-76).

Runs every catalogue check, and optionally the LLM scorer, on a directory of
message files without registering a project. A scratch config and state
directory are generated in a temporary folder, so the catalogue tree is only
ever read.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..projects import ProjectConfig
from ..projects.config import ConfigError, load_config
from ..projects.config import CONFIG_FILENAME
from .types import OpResult, QualityRequest
from .validate import op_validate
from .types import ValidateRequest

__all__ = ["op_quality", "adhoc_config"]


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def adhoc_config(req: QualityRequest, scratch: Path) -> ProjectConfig:
    """Build a config for ``req`` whose state lives in ``scratch``."""
    if not req.path_template or "{locale}" not in req.path_template:
        raise ConfigError("--path-template must contain {locale} (and {namespace} for split files)")
    if not req.source:
        raise ConfigError("--source is required with --path-template")
    targets = [t for t in (req.targets or []) if t and t != req.source]
    if not targets:
        raise ConfigError("--target is required with --path-template")
    root = Path(req.root or ".").resolve()
    template = (root / req.path_template).as_posix()
    kind = "ollama" if req.score else "null"
    lines = [
        "[project]", 'name = "quality-adhoc"', f"source_locale = {_q(req.source)}", "",
        "[catalog]", f"format = {_q(req.fmt or 'json-nested')}", f"path = {_q(template)}", "",
        "[locales]", "targets = [" + ", ".join(_q(t) for t in targets) + "]", "",
        "[provider]", f"kind = {_q(kind)}", "",
    ]
    path = scratch / CONFIG_FILENAME
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    return load_config(path)


def _report(cfg: ProjectConfig, req: QualityRequest) -> OpResult:
    result = op_validate(cfg, ValidateRequest(locales=req.locales, strict=False))
    findings = result.data.get("findings", [])
    per_locale: dict[str, dict[str, int]] = {}
    for f in findings:
        row = per_locale.setdefault(f.get("locale") or "-", {"error": 0, "warning": 0})
        row[f.get("severity") if f.get("severity") in row else "warning"] += 1
    lines = [result.summary]
    for loc in sorted(per_locale):
        row = per_locale[loc]
        lines.append(f"  {loc}: {row['error']} errors, {row['warning']} warnings")
    for f in findings[: req.limit]:
        where = ".".join(p for p in (f.get("namespace"), f.get("key")) if p)
        lines.append(f"  {f['check']} {f['severity']} {f.get('locale', '')} {where}: {f['message']}")
    if len(findings) > req.limit:
        lines.append(f"  ... {len(findings) - req.limit} more (use --format json for all)")
    data = dict(result.data)
    data["perLocale"] = per_locale
    return OpResult(
        ok=result.ok, exit_code=result.exit_code, command="quality",
        summary=result.summary, lines=lines, data=data,
    )


def op_quality(cfg: ProjectConfig | None, req: QualityRequest) -> OpResult:
    """Validate (and optionally score) a project, or an ad hoc catalogue."""
    if req.path_template:
        try:
            with tempfile.TemporaryDirectory(prefix="llm-quality-") as tmp:
                work = adhoc_config(req, Path(tmp))
                return _score_and_report(work, req)
        except ConfigError as exc:
            return OpResult(ok=False, exit_code=1, command="quality", summary=str(exc), lines=[str(exc)])
    if cfg is None:
        return OpResult(
            ok=False, exit_code=1, command="quality",
            summary="no project: pass --path-template, or run inside a project",
        )
    return _score_and_report(cfg, req)


def _score_and_report(cfg: ProjectConfig, req: QualityRequest) -> OpResult:
    out = _report(cfg, req)
    if not req.score:
        return out
    from .cloud_gate import cloud_session
    from .rescore import execute_rescore

    with cloud_session(cfg, "rescore", locales=req.locales, namespaces=None, keys=None) as blocked:
        if blocked is not None:
            return blocked
        scored = execute_rescore(cfg, locales=req.locales, model=req.model, dry_run=False)
        out.lines.append("score: " + (scored.summary or "done"))
        out.lines.extend(f"  {line}" for line in scored.lines[-10:])
        out.data["score"] = scored.data
        if not scored.ok:
            out.ok = False
            out.exit_code = max(out.exit_code, scored.exit_code)
        return out
