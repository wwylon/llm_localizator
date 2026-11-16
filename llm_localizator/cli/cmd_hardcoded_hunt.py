"""``llm-localizator hardcoded-hunt`` — dogfood pseudo + crawl/intersect."""

from __future__ import annotations

import argparse
import json

from ..ops.hardcoded_hunt import op_hardcoded_hunt
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_hardcoded_hunt(
        cfg,
        skip_crawl=bool(getattr(args, "skip_crawl", False)),
        skip_static=bool(getattr(args, "skip_static", False)),
        no_serve=not bool(getattr(args, "serve", False)),
    )
    if getattr(args, "fmt", "text") == "json":
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        for line in result.lines or []:
            print(line)
        if result.summary and result.summary not in (result.lines or []):
            print(result.summary)
    return result.exit_code
