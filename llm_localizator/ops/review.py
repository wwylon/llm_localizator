"""Review operation."""

from __future__ import annotations

from collections.abc import Callable

from ..catalog import catalog_for
from ..pipeline.review import ReviewResult, run_review
from ..projects import ProjectConfig
from ..projects.taskqueue import TaskqueueNotFound, submit, tq_available
from ..providers import project_provider
from .cloud_gate import cloud_session
from .queue_policy import should_enqueue
from .types import OpResult, ReviewRequest, resolve_namespaces

Reporter = Callable[[str], None]


def op_review(
    cfg: ProjectConfig,
    req: ReviewRequest,
    *,
    report: Reporter | None = None,
) -> OpResult:
    enqueue = (
        not req.dry_run
        and should_enqueue(submit=req.submit, inline=req.inline, tq=tq_available())
    )
    with cloud_session(
        cfg, "review", locales=req.locales,
        namespaces=resolve_namespaces(req.namespace, req.namespaces),
        batch_size=req.batch_size,
        keys=list(req.keys) if req.keys else None,
        take_hold=not enqueue,
        skip=req.dry_run,
    ) as blocked:
        if blocked is not None:
            return blocked
        return _op_review_body(cfg, req, enqueue=enqueue, report=report)


def _op_review_body(cfg, req, *, enqueue: bool, report: Reporter | None) -> OpResult:
    if enqueue:
        overrides: dict[str, str] = {}
        locales = list(req.locales) if req.locales else list(cfg.active_targets())
        if locales:
            overrides["--locales"] = ",".join(locales)
        namespaces = resolve_namespaces(req.namespace, req.namespaces)
        if namespaces and len(namespaces) == 1:
            overrides["--namespace"] = namespaces[0]
        if req.model:
            overrides["--model"] = req.model
        if req.keys:
            overrides["--keys"] = ",".join(req.keys)
        try:
            outcome = submit(cfg, "review", overrides)
            return OpResult(
                ok=outcome.ok,
                exit_code=outcome.exit_code,
                command="review",
                summary=outcome.message,
                lines=[outcome.message] if outcome.message else [],
                data={"submitted": outcome.ok, "taskIds": list(outcome.task_ids)},
            )
        except TaskqueueNotFound as exc:
            return OpResult(ok=False, exit_code=1, command="review", summary=str(exc))

    # Local run when not enqueued (tq missing or inline).
    catalog = catalog_for(cfg)
    provider = project_provider(cfg)
    lines: list[str] = []

    def _report(msg: str) -> None:
        lines.append(msg)
        if report is not None:
            report(msg)

    total = ReviewResult()
    unknown_sets: list[set[str]] = []
    for locale in cfg.resolve_locales(req.locales):
        _report(f"--- reviewing {locale} ---")
        partial = run_review(
            cfg,
            catalog,
            provider,
            locale=locale,
            namespaces=resolve_namespaces(req.namespace, req.namespaces),
            batch_size=req.batch_size,
            model=req.model,
            dry_run=req.dry_run,
            keys=list(req.keys) if req.keys else None,
            report=_report,
        )
        total.checked += partial.checked
        total.approved += partial.approved
        total.corrected += partial.corrected
        total.rejected.extend(partial.rejected)
        total.unanswered += partial.unanswered
        unknown_sets.append(set(partial.unknown_keys))

    unknown = sorted(set.intersection(*unknown_sets)) if unknown_sets and req.keys else []
    if unknown:
        _report("unknown or not reviewable keys: " + ", ".join(unknown))

    summary = (
        f"checked {total.checked}, approved {total.approved}, "
        f"corrected {total.corrected}, rejected {len(total.rejected)}"
        + (f", {total.unanswered} not answered" if total.unanswered else "")
        + (" (dry-run)" if req.dry_run else "")
    )
    return OpResult(
        ok=True,
        exit_code=0,
        command="review",
        summary=summary,
        lines=lines,
        data={
            "checked": total.checked,
            "approved": total.approved,
            "corrected": total.corrected,
            "rejected": len(total.rejected),
            "unanswered": total.unanswered,
            "unknownKeys": unknown,
            "dryRun": req.dry_run,
        },
    )
