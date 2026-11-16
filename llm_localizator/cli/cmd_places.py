"""``llm-localizator places`` — per-place translation policy (ADR-104)."""

from __future__ import annotations

import argparse
import json

from ..ops.places import op_places
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    out = op_places(cfg, args.action, args.place, args.policy)
    if args.fmt == "json":
        print(json.dumps(out.to_dict(), indent=2))
    else:
        print("\n".join(out.lines) if out.lines else out.summary)
    return out.exit_code
