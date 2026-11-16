"""``llm-localizator verify`` -- verification workflow on a disposable project copy."""

from __future__ import annotations

import argparse
import json

from ..ops.types import VerifyRequest
from ..ops.verify_run import op_verify_run

__all__ = ["run"]


def _split(value: str | None) -> list[str] | None:
    return [s.strip() for s in value.split(",") if s.strip()] if value else None


def run(args: argparse.Namespace) -> int:
    result = op_verify_run(VerifyRequest(
        path=args.path, profile=args.profile, locales=args.locales, out=args.out,
        resume=args.resume, only=_split(args.only), skip=_split(args.skip),
    ))
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        print("\n".join(result.lines))
    return result.exit_code
