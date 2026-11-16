"""``glossary-export``, ``glossary-import``, ``glossary-propose``, ``impact``, ``pseudo``."""

from __future__ import annotations

import argparse
import sys

from ..ops.glossary import op_glossary_export, op_glossary_import
from ..ops.source_ops import op_glossary_propose, op_impact, op_pseudo
from ..ops.types import GlossaryExportRequest, GlossaryImportRequest, PseudoRequest
from ..projects import resolve

__all__ = ["run_export", "run_import", "run_propose", "run_impact", "run_pseudo"]


def _cfg(args: argparse.Namespace):
    return resolve(args.project, args.config)


def _print(result) -> int:
    if not result.ok:
        print(result.summary, file=sys.stderr)
        return result.exit_code
    for line in result.lines:
        print(line)
    if result.summary and result.summary not in result.lines:
        print(result.summary)
    return result.exit_code


def run_export(args: argparse.Namespace) -> int:
    result = op_glossary_export(_cfg(args), GlossaryExportRequest(
        format=args.format, file=args.file,
    ))
    if not result.ok:
        print(result.summary, file=sys.stderr)
        return result.exit_code
    if not args.file:
        sys.stdout.write(result.data.get("text") or "")
    else:
        print(result.summary)
    return result.exit_code


def run_import(args: argparse.Namespace) -> int:
    result = op_glossary_import(_cfg(args), GlossaryImportRequest(
        format=args.format or "",
        file=args.file,
        conflict=args.conflict,
        dry_run=args.dry_run,
    ))
    return _print(result)


def run_propose(args: argparse.Namespace) -> int:
    return _print(op_glossary_propose(
        _cfg(args),
        locale=getattr(args, "locale", None),
        min_occurrences=getattr(args, "min_occurrences", 5),
        out=getattr(args, "out", None),
    ))


def run_impact(args: argparse.Namespace) -> int:
    return _print(op_impact(_cfg(args)))


def run_pseudo(args: argparse.Namespace) -> int:
    return _print(op_pseudo(_cfg(args), PseudoRequest(
        locale=args.locale,
        length_factor=args.length_factor,
        style=getattr(args, "style", "") or "",
    )))
