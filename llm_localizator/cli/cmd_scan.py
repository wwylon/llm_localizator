"""``llm-localizator scan`` -- usage backreferences and hardcoded strings."""

from __future__ import annotations

import argparse
import json

from ..ops.scan import op_scan
from ..ops.types import ScanRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_scan(cfg, ScanRequest(
        adapter=args.adapter,
        out_dir=str(args.out_dir) if args.out_dir else None,
        no_write=args.no_write,
        strict=args.strict,
        lint_directives=getattr(args, "lint_directives", False),
        surface=getattr(args, "surface", None),
    ))

    if args.fmt == "github":
        for h in result.data.get("hardcoded", []):
            print(f"::warning file={h['file']},line={h['line']},"
                  f"title=Hardcoded string::{h['reason']}: {h['text']!r}")
    elif args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        for line in result.lines:
            print(line)

    return result.exit_code
