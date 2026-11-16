"""``llm-localizator apply`` — apply catalogue additions from scan."""

from __future__ import annotations

import argparse

from ..ops.apply import op_apply
from ..ops.types import ApplyRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_apply(cfg, ApplyRequest(
        adapter=getattr(args, "adapter", None),
        limit=getattr(args, "limit", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=bool(getattr(args, "confirm", False)),
        enqueue_translate=getattr(args, "enqueue_translate", True),
    ))
    if result.exit_code != 0:
        print(result.summary)
        for line in result.lines:
            print(line)
        return result.exit_code
    print("\n".join(result.lines))
    return result.exit_code
