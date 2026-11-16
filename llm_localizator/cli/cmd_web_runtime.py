"""CLI for the shipped web runtime and the consumer key check (ADR-118)."""

from __future__ import annotations

import argparse
import json

from ..ops.web_runtime import op_check_keys, op_runtime
from ..projects import resolve

__all__ = ["run_runtime", "run_check_keys"]


def _emit(result, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": result.ok, "summary": result.summary, **result.data},
                         ensure_ascii=False, indent=2))
        return result.exit_code
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code


def run_runtime(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_runtime(cfg, args.action, force=bool(getattr(args, "force", False)),
                        path=getattr(args, "path", None))
    return _emit(result, bool(getattr(args, "json", False)))


def run_check_keys(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_check_keys(cfg, strict=bool(getattr(args, "strict", False)),
                           qa=not getattr(args, "no_qa", False))
    return _emit(result, bool(getattr(args, "json", False)))
