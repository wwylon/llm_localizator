"""Improve operation."""

from __future__ import annotations

from collections.abc import Callable

from ..catalog import catalog_for
from ..pipeline.improve import run_improve
from ..projects import ProjectConfig
from ..projects.taskqueue import TaskqueueNotFound, tq_available
from ..providers import project_provider
from .cloud_gate import cloud_session
from .enqueue import enqueue_namespace_jobs
from .queue_policy import should_enqueue
from .types import ImproveRequest, OpResult, resolve_namespaces

Reporter = Callable[[str], None]


def op_improve(
    cfg: ProjectConfig,
    req: ImproveRequest,
    *,
    report: Reporter | None = None,
) -> OpResult:
    from .tags import apply_tags

    req, early = apply_tags(cfg, req, "improve")
    if early is not None:
        return early
    enqueue = (
        not req.dry_run
        and should_enqueue(submit=req.submit, inline=req.inline, tq=tq_available())
    )
    with cloud_session(
        cfg, "improve", locales=req.locales,
        namespaces=resolve_namespaces(req.namespace, req.namespaces),
        keys=list(req.keys) if req.keys else None,
        take_hold=not enqueue,
        skip=req.dry_run,
    ) as blocked:
        if blocked is not None:
            return blocked
        return _op_improve_body(cfg, req, enqueue=enqueue, report=report)


def _op_improve_body(
    cfg: ProjectConfig,
    req: ImproveRequest,
    *,
    enqueue: bool,
    report: Reporter | None,
) -> OpResult:
    if enqueue:
        overrides: dict[str, str] = {}
        locales = list(req.locales) if req.locales else list(cfg.active_targets())
        if locales:
            overrides["--locales"] = ",".join(locales)
        if req.model:
            overrides["--model"] = req.model
        if req.limit is not None:
            overrides["--limit"] = str(req.limit)
        if req.include_rejected:
            overrides["--include-rejected"] = "true"
        if req.keys:
            overrides["--keys"] = ",".join(req.keys)
        namespaces = resolve_namespaces(req.namespace, req.namespaces)
        try:
            any_ok, messages, task_ids = enqueue_namespace_jobs(
                cfg, "improve", overrides, namespaces,
            )
            summary = messages[0] if messages else ""
            return OpResult(
                ok=any_ok,
                exit_code=0 if any_ok else 1,
                command="improve",
                summary=summary,
                lines=messages,
                data={"submitted": any_ok, "taskIds": task_ids},
            )
        except TaskqueueNotFound as exc:
            return OpResult(ok=False, exit_code=1, command="improve", summary=str(exc))

    # Local run when not enqueued (tq missing or inline). Do not hard-fail on
    # submit-without-tq — should_enqueue already chose local (ADR-158 session).
    catalog = catalog_for(cfg)
    provider = project_provider(cfg)
    lines: list[str] = []

    def _report(msg: str) -> None:
        lines.append(msg)
        if report is not None:
            report(msg)

    result = run_improve(
        cfg,
        catalog,
        provider,
        locales=req.locales,
        namespaces=resolve_namespaces(req.namespace, req.namespaces),
        limit=req.limit,
        model=req.model,
        dry_run=req.dry_run,
        include_rejected=req.include_rejected,
        keys=list(req.keys) if req.keys else None,
        report=_report,
    )
    summary = (
        f"considered {result.considered}, improved {result.improved}, "
        f"kept {result.kept_previous}"
        + (f", skipped {result.skipped_recent} cooling" if result.skipped_recent else "")
        + (" (dry-run)" if req.dry_run else "")
    )
    return OpResult(
        ok=result.exit_code == 0,
        exit_code=result.exit_code,
        command="improve",
        summary=summary,
        lines=lines + result.details[:30],
        data={
            "considered": result.considered,
            "improved": result.improved,
            "keptPrevious": result.kept_previous,
            "failed": result.failed,
            "skippedRecent": result.skipped_recent,
            "skippedExternal": [
                {"locale": loc, "namespace": ns, "key": key}
                for loc, ns, key in result.skipped_external_keys[:200]
            ],
            "dryRun": req.dry_run,
        },
    )
