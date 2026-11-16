"""``llm-localizator approach`` -- how this project can be localized (ADR-123)."""

from __future__ import annotations

import argparse
import json

from ..ops.approaches import op_approach
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_approach(cfg, set_to=getattr(args, "set_to", None))
    if getattr(args, "json", False):
        print(json.dumps({"ok": result.ok, "summary": result.summary, **result.data},
                         ensure_ascii=False, indent=2))
        return result.exit_code
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code
