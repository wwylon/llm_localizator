"""``llm-localizator patch`` — generate a structured changeset (no writes)."""

from __future__ import annotations

import argparse
import json

from ..ops.patch import op_patch
from ..ops.types import PatchRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_patch(cfg, PatchRequest(
        adapter=getattr(args, "adapter", None),
        limit=getattr(args, "limit", None),
        out_dir=getattr(args, "out_dir", None),
        fmt=getattr(args, "fmt", "text") or "text",
    ))
    if result.exit_code != 0:
        if result.summary:
            print(result.summary)
        return result.exit_code
    if getattr(args, "fmt", "text") == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        print("\n".join(result.lines))
    return result.exit_code
