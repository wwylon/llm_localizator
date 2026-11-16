"""``llm-localizator adopt`` — stamp catalogue-only keys into state (no LLM)."""

from __future__ import annotations

import argparse
import json

from ..ops.adopt import op_adopt
from ..ops.types import AdoptRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_adopt(
        cfg,
        AdoptRequest(
            locales=args.locales,
            namespace=args.namespace,
            namespaces=[args.namespace] if args.namespace else None,
            dry_run=args.dry_run,
            limit=args.limit,
            model=getattr(args, "model", None) or "cursor-agent",
            provider=getattr(args, "provider", None) or "agent",
            verified_by=getattr(args, "verified_by", None) or "cursor-agent",
        ),
    )
    if getattr(args, "fmt", "text") == "json":
        print(json.dumps(result.data, indent=2))
    else:
        if result.summary:
            print(result.summary)
        for line in result.lines:
            print(line)
    return result.exit_code
