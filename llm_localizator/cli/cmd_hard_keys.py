"""``llm-localizator hard-keys`` — cross-locale score triage report."""

from __future__ import annotations

import argparse
import json

from ..ops.hard_keys import op_hard_keys
from ..ops.types import HardKeysRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_hard_keys(
        cfg,
        HardKeysRequest(
            locales=args.locales,
            namespace=args.namespace,
            namespaces=[args.namespace] if args.namespace else None,
            threshold=args.threshold,
            min_locales=args.min_locales,
            dry_run=args.dry_run,
        ),
        report=print,
    )
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2))
    elif result.summary:
        print(result.summary)
    return result.exit_code
