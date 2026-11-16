"""Sync operation."""

from __future__ import annotations

from ..catalog import catalog_for
from ..pipeline.sync import run_sync
from ..projects import ProjectConfig
from ..projects.taskqueue import TaskqueueNotFound, submit
from .types import OpResult, SyncRequest


def op_sync(cfg: ProjectConfig, req: SyncRequest) -> OpResult:
    catalog = catalog_for(cfg)
    lines: list[str] = []

    def report(msg: str) -> None:
        lines.append(msg)

    result = run_sync(
        cfg,
        catalog,
        locales=req.locales,
        dry_run=req.dry_run,
        submit_translate=req.submit_translate and not req.no_translate,
        strict_branch=req.strict_branch,
        diff=req.diff,
        exit_nonzero=req.exit_nonzero,
        report=report,
    )
    if req.submit_translate and not req.dry_run and not req.no_translate:
        try:
            outcome = submit(cfg, "sync")
            lines.append(outcome.message or f"sync submit exit {outcome.exit_code}")
        except TaskqueueNotFound as exc:
            return OpResult(
                ok=False,
                exit_code=1,
                command="sync",
                summary=str(exc),
                lines=lines,
            )
    if req.diff and not req.dry_run and (
        result.manifest_added or result.manifest_changed or result.manifest_removed
    ):
        from .notify import notify_project

        notify_project(cfg, {
            "event": "source.changed",
            "project": cfg.name,
            "added": result.manifest_added,
            "changed": result.manifest_changed,
            "removed": result.manifest_removed,
        }, wait=True)
    summary = f"backlog {result.missing_or_stale} key-locale pair(s)"
    if result.dry_run:
        summary += " (dry-run)"
    return OpResult(
        ok=True,
        exit_code=result.exit_code,
        command="sync",
        summary=summary,
        lines=lines + result.details[:50],
        data={
            "usages": result.usages,
            "hardcoded": result.hardcoded,
            "missingOrStale": result.missing_or_stale,
            "dryRun": result.dry_run,
            "translateSubmitted": result.translate_submitted,
            "branchWarning": result.branch_warning,
            "manifest": result.manifest_file,
            "manifestAdded": result.manifest_added,
            "manifestChanged": result.manifest_changed,
            "manifestRemoved": result.manifest_removed,
        },
    )
