"""``llm-localizator explain-scan FILE[:LINE]`` — why the hardcoded-string scanner did or did not report a line."""

from __future__ import annotations

import argparse
import json

from ..ops.explain_scan import ExplainScanRequest, op_explain_scan
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_explain_scan(cfg, ExplainScanRequest(target=args.target, adapter=args.adapter))
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        print("\n".join(result.lines) if result.lines else result.summary)
    return result.exit_code
