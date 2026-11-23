"""``llm-localizator localize-project`` -- the localization checklist as one report."""

from __future__ import annotations

import argparse
import json
import sys

from ..ops.localize_project import LocalizeProjectRequest, op_localize_project
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_localize_project(cfg, LocalizeProjectRequest(
        locales=args.locales, submit=getattr(args, "submit", False),
        baseline=getattr(args, "baseline", False)))
    if getattr(args, "fmt", "text") == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False, default=str))
        return result.exit_code
    if not result.ok and result.summary:
        print(result.summary, file=sys.stderr)
    for line in result.lines:
        print(line)
    return result.exit_code
