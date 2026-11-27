"""Shared enqueue-vs-inline policy for LLM ops (ADR-28 / Wave 3)."""

from __future__ import annotations

from ..projects.taskqueue import tq_available

__all__ = ["should_enqueue"]


def should_enqueue(
    *,
    submit: bool,
    inline: bool,
    dry_run: bool = False,
    tq: bool | None = None,
) -> bool:
    """Return True when the op should submit to taskqueue instead of running here.

    Enqueue only when ``tq`` is on PATH. Prefer the queue when the operator asked
    to submit, or when ``tq`` is available and the caller did not force
    ``inline`` (``run-*`` paths). Without ``tq``, callers fall through to a
    local run — the engine must work without taskqueue installed.

    Pass ``tq=`` explicitly so tests can monkeypatch the caller's ``tq_available``.
    """
    if dry_run:
        return False
    available = tq_available() if tq is None else tq
    if not available:
        return False
    return bool(submit or not inline)
