"""``open-pr``: send changed catalogue files as a pull request (C-015, ADR-101)."""

from __future__ import annotations

import argparse
import json
import sys

from ..ops.open_pr import op_open_pr
from ..ops.types import OpenPrRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    # `cmd link` parses `link` as the optional project positional; treat it as the action.
    if args.project in ("plan", "open", "status") and args.action == ("plan", "open", "status")[0]:
        args.action, args.project = args.project, None
    result = op_open_pr(resolve(args.project, args.config), OpenPrRequest(
        action=args.action, branch=args.pr_branch or "", confirm=args.yes,
    ))
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
        return result.exit_code
    if not result.ok:
        print(result.summary, file=sys.stderr)
        return result.exit_code
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code
