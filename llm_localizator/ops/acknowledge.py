"""Clear an interrupted flush journal without writing catalogues."""

from __future__ import annotations

from ..catalog.flush_journal import FlushJournal
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["op_acknowledge_flush"]


def op_acknowledge_flush(cfg: ProjectConfig) -> OpResult:
    journal = FlushJournal(cfg.state_root())
    removed = journal.acknowledge()
    if removed:
        summary = "flush journal deleted; catalogues were not written"
    else:
        summary = "no flush journal"
    return OpResult(
        ok=True,
        exit_code=0,
        command="acknowledge-flush",
        summary=summary,
        lines=[summary],
    )
