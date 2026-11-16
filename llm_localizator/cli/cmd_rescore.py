"""``llm-localizator rescore`` / ``run-rescore`` — refresh quality scores via BT."""

from __future__ import annotations

import argparse

from ..ops.rescore import op_rescore
from ..ops.types import RescoreRequest, parse_csv_list
from ..projects import resolve

__all__ = ["run_submit", "run_execute"]


def run_submit(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_rescore(cfg, RescoreRequest(
        locales=list(getattr(args, "locales", None) or []) or None,
        namespace=getattr(args, "namespace", None),
        model=getattr(args, "model", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        submit=not bool(getattr(args, "dry_run", False)),
        stale_only=bool(getattr(args, "stale_only", False)),
        below_score=getattr(args, "below_score", None),
        keys=parse_csv_list(getattr(args, "keys", None)),
    ))
    if result.summary:
        print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code


def run_execute(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_rescore(cfg, RescoreRequest(
        locales=args.locales,
        namespace=getattr(args, "namespace", None),
        model=getattr(args, "model", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        stale_only=bool(getattr(args, "stale_only", False)),
        below_score=getattr(args, "below_score", None),
        keys=parse_csv_list(getattr(args, "keys", None)),
        inline=True,
    ))
    return result.exit_code
