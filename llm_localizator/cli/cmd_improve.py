"""``llm-localizator improve`` / ``run-improve`` — raise low auto-scores overnight."""

from __future__ import annotations

import argparse

from ..ops.improve import op_improve
from ..ops.types import ImproveRequest, parse_csv_list
from ..projects import resolve

__all__ = ["run_submit", "run_execute"]


def run_submit(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    keys = parse_csv_list(getattr(args, "keys", None))
    result = op_improve(cfg, ImproveRequest(
        locales=list(getattr(args, "locales", None) or []) or None,
        namespace=getattr(args, "namespace", None),
        model=getattr(args, "model", None),
        limit=getattr(args, "limit", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        submit=not bool(getattr(args, "dry_run", False)),
        include_rejected=bool(getattr(args, "include_rejected", False)),
        keys=keys,
        tags=parse_csv_list(getattr(args, "tags", None)),
    ))
    if result.summary:
        print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code


def run_execute(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_improve(cfg, ImproveRequest(
        locales=args.locales,
        namespace=args.namespace,
        model=args.model,
        limit=args.limit,
        dry_run=args.dry_run,
        include_rejected=bool(getattr(args, "include_rejected", False)),
        keys=parse_csv_list(getattr(args, "keys", None)),
        tags=parse_csv_list(getattr(args, "tags", None)),
        inline=True,
    ))
    return result.exit_code
