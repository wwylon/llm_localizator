"""Source-side review: ``flag-source`` and ``source-review-queue`` (ADR-53).

A flag is a review ticket on the source locale, so it never reaches ``translate --flagged``
(that store is per target locale and drives retranslation).
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.review_queue import open_review_queue
from ..projects import ProjectConfig
from .types import FlagSourceRequest, OpResult, SourceReviewQueueRequest

__all__ = ["SOURCE_REVIEW_REASON", "op_flag_source", "op_source_review_queue"]

SOURCE_REVIEW_REASON = "source-review"


def op_flag_source(cfg: ProjectConfig, req: FlagSourceRequest) -> OpResult:
    if not (req.namespace and req.key):
        return OpResult(ok=False, exit_code=64, command="flag-source",
                        summary="flag-source needs namespace and key")
    catalog = catalog_for(cfg)
    source = catalog.load(cfg.source_locale, req.namespace).get(req.key)
    if not isinstance(source, str):
        return OpResult(ok=False, exit_code=64, command="flag-source",
                        summary=f"{req.namespace}.{req.key} not found in the source catalogue")
    note = (req.note or "").strip()
    reason = f"{SOURCE_REVIEW_REASON}: {note}" if note else SOURCE_REVIEW_REASON
    ticket = open_review_queue(cfg).enqueue(
        locale=cfg.source_locale, namespace=req.namespace, key=req.key,
        reason=reason, source=source,
    )
    return OpResult(
        ok=True, exit_code=0, command="flag-source",
        summary=f"flagged {req.namespace}.{req.key} for source review",
        data={"ticket": ticket.id, "reason": ticket.reason},
    )


def op_source_review_queue(cfg: ProjectConfig, req: SourceReviewQueueRequest) -> OpResult:
    tickets = [
        t for t in open_review_queue(cfg).open_tickets(cfg.source_locale)
        if t.reason.startswith(SOURCE_REVIEW_REASON)
    ]
    rows = [
        {"id": t.id, "namespace": t.namespace, "key": t.key, "reason": t.reason,
         "source": t.source, "assignee": t.assignee, "createdAt": t.created_at}
        for t in tickets
    ]
    return OpResult(
        ok=True, exit_code=0, command="source-review-queue",
        summary=f"{len(rows)} source string(s) flagged for review",
        lines=[f"{r['namespace']}.{r['key']}: {r['reason']}" for r in rows],
        data={"tickets": rows},
    )
