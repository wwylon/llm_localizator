"""Ingest consumer visual findings into the review queue (ADR-27)."""

from __future__ import annotations


from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.review_queue import open_review_queue
from ..catalog.visual_findings import VisualFindingsError, iter_findings
from ..projects import ProjectConfig
from .screenshot_link import attach_screenshot
from .types import IngestVisualRequest, OpResult
from ..projects.paths import project_path


def op_ingest_visual(cfg: ProjectConfig, req: IngestVisualRequest) -> OpResult:
    path = project_path(cfg.root, req.path) or cfg.findings_path()
    if not path.is_absolute():
        path = (cfg.root / path).resolve()
    if not path.exists():
        return OpResult(
            ok=False,
            exit_code=1,
            command="ingest-visual",
            summary=f"findings file not found: {path}",
            lines=[f"error: no file at {path}"],
            data={"path": str(path), "enqueued": 0, "skipped": 0},
        )

    queue = open_review_queue(cfg)
    seen: set[tuple[str, str, str, str]] = set()
    enqueued = 0
    skipped = 0
    lines: list[str] = []
    errors: list[str] = []

    try:
        findings = list(iter_findings(path))
    except VisualFindingsError as exc:
        return OpResult(
            ok=False,
            exit_code=1,
            command="ingest-visual",
            summary=str(exc),
            lines=[f"error: {exc}"],
            data={"path": str(path), "enqueued": 0, "skipped": 0},
        )

    for finding in findings:
        ns = finding.ticket_namespace()
        key = finding.ticket_key()
        dedupe = (finding.locale, ns, key, finding.reason)
        if dedupe in seen:
            skipped += 1
            continue
        seen.add(dedupe)
        if req.dry_run:
            lines.append(
                f"dry-run {finding.locale}/{ns}.{key}: {finding.reason} — {finding.message}"
            )
            enqueued += 1
            continue
        comment = finding.message
        if finding.screenshot:
            comment = f"{comment} (screenshot={finding.screenshot})"
        if finding.path:
            comment = f"{comment} [path={finding.path}]"
        ticket = queue.enqueue(
            locale=finding.locale,
            namespace=ns,
            key=key,
            reason=finding.reason,
            source=finding.source,
            current=comment,
        )
        queue.add_comment(
            finding.locale,
            ticket.id,
            finding.source or "ingest-visual",
            comment,
        )
        if finding.screenshot and finding.namespace and finding.key:
            # C-012: a finding that names a real key also links its screenshot to it (no region).
            with project_mutation_lock(cfg):
                attach_screenshot(cfg, finding.screenshot, ns, key, note=finding.message, by=finding.source or "ingest-visual")
        lines.append(f"enqueued {finding.locale}/{ns}.{key}: {finding.reason}")
        enqueued += 1

    if errors:
        lines.extend(errors)
    summary = (
        f"{'would enqueue' if req.dry_run else 'enqueued'} {enqueued} ticket(s) "
        f"from {path.name}"
        + (f", skipped {skipped} duplicate(s)" if skipped else "")
    )
    return OpResult(
        ok=True,
        exit_code=0,
        command="ingest-visual",
        summary=summary,
        lines=lines,
        data={
            "path": str(path),
            "enqueued": enqueued,
            "skipped": skipped,
            "dryRun": req.dry_run,
        },
    )
