"""``llm-localizator bakeoff`` / ``run-bakeoff`` — compare local models on your own strings."""

from __future__ import annotations

import argparse

from ..ops.bakeoff import op_bakeoff
from ..ops.types import BakeoffRequest
from ..projects import resolve
from ..projects.taskqueue import TaskqueueNotFound
from .output import print_result

__all__ = ["run_submit", "run_execute"]


def _request(args: argparse.Namespace, *, inline: bool) -> BakeoffRequest:
    return BakeoffRequest(
        locales=getattr(args, "locales", None),
        models=getattr(args, "models", None),
        limit=getattr(args, "limit", 30) or 30,
        corpus=getattr(args, "corpus", None),
        slice=getattr(args, "slice", None),
        out=getattr(args, "out", None),
        family=getattr(args, "family", None),
        matrix=bool(getattr(args, "matrix", False)),
        force_cells=bool(getattr(args, "force_cells", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        inline=inline,
        propose_config=bool(getattr(args, "propose_config", False)),
    )


def run_submit(args: argparse.Namespace) -> int:
    """``bakeoff``: queue it when ``tq`` exists, else run it here (ADR-15)."""
    cfg = resolve(args.project, args.config)
    try:
        return print_result(op_bakeoff(cfg, _request(args, inline=False), report=print))
    except TaskqueueNotFound as exc:
        print(f"error: {exc}")
        return 1


def run_execute(args: argparse.Namespace) -> int:
    """``run-bakeoff``: always in this process (what the queue invokes)."""
    cfg = resolve(args.project, args.config)
    return print_result(op_bakeoff(cfg, _request(args, inline=True), report=print))
