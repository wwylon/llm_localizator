"""``llm-localizator analytics`` — run speed and verify/score lag summaries."""

from __future__ import annotations

import argparse
import json

from ..ops.analytics import op_analytics
from ..ops.types import AnalyticsRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_analytics(
        cfg,
        AnalyticsRequest(
            since=args.since,
            run_command=args.run_command,
            locale=args.locale,
            locales=args.locales,
            model=args.model,
            last=args.last,
            fmt=args.fmt,
        ),
    )

    if args.fmt == "json":
        print(json.dumps(result.data, indent=2))
    else:
        for line in result.lines:
            print(line)
    return result.exit_code
