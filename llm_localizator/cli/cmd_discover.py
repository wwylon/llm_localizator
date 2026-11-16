"""``llm-localizator discover`` — propose locale directories. Writes nothing."""

from __future__ import annotations

import argparse
import json

from ..ops.discover import op_discover
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_discover(cfg)
    if getattr(args, "fmt", "text") == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        print("\n".join(result.lines))
    return result.exit_code
