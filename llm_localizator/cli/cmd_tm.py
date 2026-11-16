"""``concordance``, ``tm-export``, and ``tm-import``."""

from __future__ import annotations

import argparse
import json
import sys

from ..ops.tm import op_concordance, op_tm_export, op_tm_import
from ..ops.types import ConcordanceRequest, TmExportRequest, TmImportRequest
from ..projects import resolve

__all__ = ["run_concordance", "run_export", "run_import"]


def _cfg(args: argparse.Namespace):
    return resolve(args.project, args.config)


def run_concordance(args: argparse.Namespace) -> int:
    result = op_concordance(_cfg(args), ConcordanceRequest(
        locale=args.locale,
        query=args.query,
        source=not args.no_source,
        target=not args.no_target,
        limit=args.limit,
        mode="fuzzy" if args.min_similarity is not None else "substring",
        min_similarity=args.min_similarity if args.min_similarity is not None else 0.55,
    ))
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        if not result.ok:
            print(result.summary, file=sys.stderr)
        for line in result.lines:
            print(line)
        if result.ok:
            print(result.summary)
    return result.exit_code


def run_export(args: argparse.Namespace) -> int:
    result = op_tm_export(_cfg(args), TmExportRequest(locale=args.locale, path=args.out))
    if not result.ok:
        print(result.summary, file=sys.stderr)
        return result.exit_code
    if not args.out:
        sys.stdout.write(result.data.get("tmx") or "")
    else:
        print(result.summary)
    return result.exit_code


def run_import(args: argparse.Namespace) -> int:
    result = op_tm_import(_cfg(args), TmImportRequest(
        locale=args.locale,
        path=args.file,
        conflict=args.conflict,
        dry_run=args.dry_run,
    ))
    if not result.ok:
        print(result.summary, file=sys.stderr)
    else:
        print(result.summary)
    return result.exit_code
