"""Per-run mutable context — keeps runtime fields off ProjectConfig."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunContext:
    """Mutable state for one translate / improve / rescore / flush pass.

    ProjectConfig stays the immutable TOML view; attach this when a run needs
    a flush journal id or other ephemeral knobs (ADR deep-health Wave 2).
    """

    run_id: str = "flush"
    flush_run_id: str = ""
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.flush_run_id:
            self.flush_run_id = self.run_id or "flush"


def flush_run_id_of(cfg, ctx: RunContext | None = None) -> str:
    """Resolve the journal run id from an explicit context or legacy cfg attr."""
    if ctx is not None and ctx.flush_run_id:
        return ctx.flush_run_id
    return getattr(cfg, "_flush_run_id", "") or "flush"
