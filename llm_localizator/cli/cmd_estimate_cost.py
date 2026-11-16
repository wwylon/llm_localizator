"""``llm-localizator estimate-cost`` — maximum cloud USD, no API call."""

from __future__ import annotations

import argparse
import json
import sys

from ..ops.estimate_cost import op_estimate_cost
from ..ops.types import EstimateCostRequest, parse_csv_list
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_estimate_cost(cfg, EstimateCostRequest(
        locales=args.locales,
        namespace=args.namespace,
        collection=getattr(args, "collection", None),
        keys=parse_csv_list(getattr(args, "keys", None)),
        batch_size=getattr(args, "batch_size", None) or cfg.translate_batch_size or 10,
        purpose=getattr(args, "purpose", "translate") or "translate",
    ))
    if getattr(args, "fmt", "text") == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
        return result.exit_code
    if not result.ok and result.summary:
        print(result.summary, file=sys.stderr)
    for line in result.lines:
        print(line)
    return result.exit_code
