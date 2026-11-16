"""``llm-localizator engine`` -- the provider and model for every pipeline role (ADR-156)."""

from __future__ import annotations

import argparse
import json

from ..ops.engines import op_engine
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_engine(
        cfg, args.action, args.engine_id,
        accept_unbenchmarked=bool(getattr(args, "accept_unbenchmarked", False)),
        vram=getattr(args, "vram", None), gpu_busy=bool(getattr(args, "gpu_busy", False)),
        url=getattr(args, "url", None), write=bool(getattr(args, "write", False)),
        accept_unverified=bool(getattr(args, "accept_unverified", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps({"ok": result.ok, "summary": result.summary, **result.data},
                         ensure_ascii=False, indent=2, default=str))
        return result.exit_code
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code
