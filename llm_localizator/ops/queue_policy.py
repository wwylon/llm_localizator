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

    Matches translate/bakeoff: enqueue when the operator asked to submit, or when
    ``tq`` is on PATH and the caller did not force ``inline`` (``run-*`` paths).

    Pass ``tq=`` explicitly so tests can monkeypatch the caller's ``tq_available``.
    """
    if dry_run:
        return False
    available = tq_available() if tq is None else tq
    return bool(submit or (available and not inline))
