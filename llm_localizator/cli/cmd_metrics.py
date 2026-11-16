"""``llm-localizator metrics`` — edit rate, cycle time and coverage trend."""

from __future__ import annotations

import argparse
import json

from ..ops.metrics import op_metrics
from ..ops.types import MetricsRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_metrics(cfg, MetricsRequest(
        by=args.by, since=args.since, locale=args.locale, locales=args.locales, fmt=args.fmt,
        why_low=args.why_low, threshold=args.threshold,
    ))
    if args.fmt == "csv":
        if not args.by:
            print("--format csv needs --by")
            return 1
        print(result.data.get("csv", ""), end="")
    elif args.fmt == "json":
        print(json.dumps(result.data, indent=2))
    else:
        print(result.summary)
        for line in result.lines:
            print(line)
    return result.exit_code
