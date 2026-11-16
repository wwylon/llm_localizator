"""Validate operation."""

from __future__ import annotations

from pathlib import Path

from ..catalog import FlagStore, catalog_for
from ..pipeline.validate import SEVERITY_ERROR, run_validation
from ..projects import ProjectConfig
from .types import OpResult, ValidateRequest


def _finding_dict(f, *, root: Path | None = None) -> dict:
    path = f.file
    if path and root is not None:
        try:
            path = Path(path).resolve().relative_to(Path(root).resolve())
        except (OSError, ValueError):
            path = Path(path).name if path else None
    return {
        "check": f.check,
        "severity": f.severity,
        "locale": f.locale,
        "namespace": f.namespace,
        "key": f.key,
        "message": f.message,
        "file": str(path) if path else None,
    }


def _by_check(findings) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.check] = counts.get(f.check, 0) + 1
    return counts


def write_flags(cfg, report, checks: set[str]) -> int:
    """Append selected findings to ``cfg.flags_path``. Returns rows written."""
    if not cfg.flags_path:
        return 0
    from ..catalog.mutation_lock import project_mutation_lock

    with project_mutation_lock(cfg):
        return FlagStore(cfg.flags_path).append_findings(report.findings, checks)


def op_validate(cfg: ProjectConfig, req: ValidateRequest, *, catalog=None) -> OpResult:
    if catalog is None:
        catalog = catalog_for(cfg)
    changed = None
    if req.diff_scope is not None:
        changed = {Path(p) for p in req.diff_scope}
    namespaces = req.namespaces
    if not namespaces and req.namespace:
        namespaces = [req.namespace]
    semantic = req.semantic
    report = run_validation(
        cfg,
        catalog,
        locales=req.locales,
        namespace=req.namespace if not namespaces else None,
        namespaces=namespaces,
        changed_files=changed,
        check_expansion=req.check_expansion or req.check_length or semantic,
        check_semantic=semantic,
        check_script=req.check_script,
        check_digraphs=req.check_digraphs,
        check_length_semantic=req.check_length or semantic,
        check_layout=req.check_layout,
        check_numbers=req.check_numbers,
        diff_only=req.diff_only,
    )
    unused_note = None
    if req.unused and not report.scope_error:
        from .unused import find_unused

        found, unused_note = find_unused(cfg, catalog, namespaces)
        report.findings.extend(found)
        if cfg.severity_overrides:
            from ..pipeline.validate import apply_severity_overrides

            report.findings = apply_severity_overrides(report.findings, cfg.severity_overrides)
    if report.scope_error:
        lines = [f"ERROR  {report.scope_error}"]
        return OpResult(
            ok=False,
            exit_code=1,
            command="validate",
            summary=report.scope_error,
            lines=lines,
            data={
                "scopeError": report.scope_error,
                "checkedKeys": 0,
                "checkedLocales": report.checked_locales,
                "errors": 1,
                "warnings": 0,
                "findings": [],
                "byCheck": {},
                "flagsWritten": 0,
            },
        )
    detail = (req.detail or "full").strip().lower()
    summary_only = detail == "summary"
    limit = req.findings_limit
    if limit is None and not summary_only:
        limit = None
    elif limit is not None:
        limit = max(0, int(limit))
    findings = list(report.findings)
    truncated = False
    if summary_only:
        shown = []
        lines = []
    else:
        if limit is not None and len(findings) > limit:
            shown = findings[:limit]
            truncated = True
        else:
            shown = findings
        lines = [
            f"{'ERROR' if f.severity == SEVERITY_ERROR else 'warn '} [{f.check}] {f.location()}: {f.message}"
            for f in shown
        ]
    if unused_note and not summary_only:
        lines.append(unused_note)
    flags_written = 0
    if req.write_flags:
        checks = {c.strip() for c in req.flag_checks.split(",") if c.strip()}
        flags_written = write_flags(cfg, report, checks)
        if not summary_only:
            if cfg.flags_path:
                lines.append(f"wrote {flags_written} new flag(s)")
            else:
                lines.append("warn: no [state] flags path configured; skipping --write-flags")
    parts = [f"{report.checked_keys} keys", f"{len(report.checked_locales)} locales"]
    if report.errors:
        parts.append(f"{len(report.errors)} errors")
    if report.warnings:
        parts.append(f"{len(report.warnings)} warnings")
    if not report.errors and not report.warnings:
        parts.append("clean")
    summary = "checked " + ", ".join(parts)
    exit_code = report.exit_code(strict=req.strict)
    data = {
        "checkedKeys": report.checked_keys,
        "checkedLocales": report.checked_locales,
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "byCheck": _by_check(findings),
        "flagsWritten": flags_written,
        "findingsTruncated": truncated,
        "findingsTotal": len(findings),
    }
    if not summary_only:
        data["findings"] = [_finding_dict(f, root=cfg.root) for f in shown]
    else:
        data["findings"] = []
    return OpResult(
        ok=exit_code == 0,
        exit_code=exit_code,
        command="validate",
        summary=summary,
        lines=lines,
        data=data,
    )
