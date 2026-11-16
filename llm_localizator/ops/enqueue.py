"""Shared taskqueue submit for translate, improve, and rescore.

Translate still submits one task per locale (ADR-15). Improve and rescore
keep one task that lists every locale.
"""

from __future__ import annotations

from ..projects import ProjectConfig
from ..projects.taskqueue import submit, submit_locales
from .types import namespace_override_sets


def enqueue_namespace_jobs(
    cfg: ProjectConfig,
    job: str,
    overrides: dict[str, str],
    namespaces: list[str] | None,
    *,
    locales: list[str] | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Submit once per namespace fragment.

    When ``locales`` is set, each locale is its own queue task and messages
    are split into lines. Otherwise one task carries the locale list already
    in ``overrides``.
    """
    messages: list[str] = []
    task_ids: list[str] = []
    any_ok = False
    for ns_ov in namespace_override_sets(namespaces):
        ov = {**overrides, **ns_ov}
        if locales is not None:
            outcome = submit_locales(cfg, locales, job, ov or None)
            if outcome.message:
                messages.extend(ln for ln in outcome.message.splitlines() if ln)
        else:
            outcome = submit(cfg, job, ov)
            if outcome.message:
                messages.append(outcome.message)
        task_ids.extend(outcome.task_ids)
        if outcome.ok:
            any_ok = True
    return any_ok, messages, task_ids
