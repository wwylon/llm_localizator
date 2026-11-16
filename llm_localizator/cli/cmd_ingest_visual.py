"""``llm-localizator ingest-visual`` — load consumer findings into the review queue."""

from __future__ import annotations

import argparse

from ..ops.ingest_visual import op_ingest_visual
from ..ops.types import IngestVisualRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_ingest_visual(cfg, IngestVisualRequest(
        path=getattr(args, "path", None),
        dry_run=bool(getattr(args, "dry_run", False)),
    ))
    for line in result.lines:
        print(line)
    print(result.summary)
    return result.exit_code
