"""``llm-localizator queue-engine`` -- rewrite existing taskqueue blueprints for one engine (W3)."""

from __future__ import annotations

import argparse

from ..ops.queue import op_queue_engine
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_queue_engine(cfg, args.engine_id, dry_run=bool(getattr(args, "dry_run", False)))
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code
