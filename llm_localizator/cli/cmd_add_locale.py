"""``llm-localizator add-locale`` — add a target locale to the project config."""

from __future__ import annotations

import argparse
import sys

from ..ops.add_locale import add_locale
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = add_locale(cfg, args.locale, getattr(args, "model", None))
    if not result.get("ok"):
        print(result.get("error") or "add-locale failed", file=sys.stderr)
        return 1
    print(f"added {args.locale}")
    return 0
