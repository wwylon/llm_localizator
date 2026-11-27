"""CLI for term-report and release snapshots."""

from __future__ import annotations

import argparse

from ..ops.release import op_release_diff, op_release_freeze
from ..ops.terminology import op_term_report
from ..ops.types import parse_csv_list
from ..projects import resolve
from .output import print_result

__all__ = ["run_term_report", "run_release_freeze", "run_release_diff"]


def run_term_report(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_term_report(cfg, locales=parse_csv_list(getattr(args, "locales", None)))
    return print_result(result, as_json=bool(getattr(args, "json", False)))


def run_release_freeze(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    try:
        result = op_release_freeze(
            cfg,
            name=args.name,
            namespaces=parse_csv_list(getattr(args, "namespaces", None)),
            keys=parse_csv_list(getattr(args, "keys", None)),
        )
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    return print_result(result)


def run_release_diff(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    try:
        result = op_release_diff(cfg, name=args.name)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    return print_result(result)
