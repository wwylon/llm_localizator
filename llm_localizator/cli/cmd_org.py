"""``org``: organisation-level TM and glossary status (C-036, ADR-99)."""

from __future__ import annotations

import argparse
import json
import sys

from ..ops.org import op_org
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    result = op_org(resolve(args.project, args.config))
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
        return result.exit_code
    if not result.ok:
        print(result.summary, file=sys.stderr)
        return result.exit_code
    for line in result.lines:
        print(line)
    return result.exit_code
