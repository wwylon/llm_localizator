"""``llm-localizator workflow`` -- run a named workflow script from the terminal."""

from __future__ import annotations

import argparse
import json

from ..ops.workflow import WorkflowRequest, op_workflow_run
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    if getattr(args, "list_presets", False):
        from ..core.workflow_rules import presets

        rows = presets()
        if args.fmt == "json":
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for row in rows:
                print(f"{row['id']:<18}{row['label']}")
        return 0
    cfg = resolve(args.project, args.config)
    result = op_workflow_run(cfg, WorkflowRequest(
        name=args.workflow_name,
        locales=args.locales,
        namespace=args.namespace,
        dry_run=args.dry_run,
        route_only=args.route_only,
        submit=args.submit,
        inline=args.inline,
        resume=args.resume,
    ))
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2, default=str))
    else:
        print(result.summary)
        for line in result.lines:
            print(line)
    return result.exit_code
