"""``llm-localizator validate`` -- catalogue checks, no LLM required."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..ops.types import ValidateRequest
from ..ops.validate import op_validate
from ..pipeline.validate import SEVERITY_ERROR
from ..projects import resolve

__all__ = ["run"]


def _diff_scope(values: list[str] | None) -> list[str] | None:
    """Resolve ``--diff-scope``; with no arguments, read paths from stdin."""
    if values is None:
        return None
    if values:
        return [str(Path(v).resolve()) for v in values]
    if sys.stdin.isatty():
        raise ValueError(
            "--diff-scope needs file paths as arguments or piped on stdin "
            "(stdin is a terminal)"
        )
    return [str(Path(line.strip()).resolve()) for line in sys.stdin if line.strip()]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    diff_scope = _diff_scope(args.diff_scope)
    result = op_validate(cfg, ValidateRequest(
        locales=args.locales,
        namespace=args.namespace,
        strict=args.strict,
        check_expansion=args.check_expansion,
        check_layout=getattr(args, "check_layout", False),
        check_numbers=getattr(args, "check_numbers", False),
        diff_only=getattr(args, "diff_only", False),
        semantic=getattr(args, "semantic", False),
        write_flags=getattr(args, "write_flags", False),
        flag_checks=args.flag_checks or "V13",
        diff_scope=diff_scope,
        unused=getattr(args, "unused", False),
    ))

    if args.fmt == "github":
        for f in result.data.get("findings", []):
            level = "error" if f.get("severity") == SEVERITY_ERROR else "warning"
            loc = f"file={f['file']}," if f.get("file") else ""
            title = f"{f['check']} {f.get('locale', '')}/{f.get('namespace', '')}.{f.get('key', '')}"
            message = str(f.get("message", "")).replace("\n", " ")
            print(f"::{level} {loc}title={title}::{message}")
    elif args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        if not args.quiet:
            for line in result.lines:
                if not line.startswith("wrote "):
                    print(line)
        print(result.summary)

    if getattr(args, "write_flags", False):
        checks = {c.strip() for c in (args.flag_checks or "V13").split(",") if c.strip()}
        n = result.data.get("flagsWritten", 0)
        if cfg.flags_path:
            print(
                f"wrote {n} new flag(s) to {cfg.flags_path} "
                f"(checks={','.join(sorted(checks))})"
            )
        else:
            print("warn: no [state] flags path configured; skipping --write-flags")

    return result.exit_code
