"""CLI entry points for ``suggest``, ``flag-source``, ``source-review-queue``, ``bulk-clear``."""

from __future__ import annotations

import argparse
import json

from ..ops.apply_near import op_apply_near
from ..ops.draft import op_draft
from ..ops.find_replace import op_find_replace
from ..ops.task import op_task
from ..ops.bulk_clear import op_bulk_clear
from ..ops.placeholder_rename import op_rename_placeholder
from ..ops.scan_decide import op_scan_decide
from ..ops.source_review import op_flag_source, op_source_review_queue
from ..ops.discuss import op_discuss
from ..ops.source_diff import op_source_diff
from ..ops.suggest import op_suggest
from ..ops.types import (
    ApplyNearRequest,
    DraftRequest,
    FindReplaceRequest,
    TaskRequest,
    DiscussRequest,
    BulkClearRequest,
    PlaceholderRenameRequest,
    FlagSourceRequest,
    OpResult,
    ScanDecideRequest,
    SourceReviewQueueRequest,
    SuggestRequest,
)
from ..projects import resolve

__all__ = [
    "run_suggest", "run_draft", "run_task", "run_discuss", "run_flag_source", "run_source_review_queue", "run_bulk_clear", "run_apply_near", "run_find_replace", "run_rename_placeholder", "run_scan_decide",
]


def _print(result: OpResult, args: argparse.Namespace) -> int:
    from .output import print_result

    return print_result(result, as_json=getattr(args, "fmt", "text") == "json")


def run_suggest(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_suggest(cfg, SuggestRequest(
        locale=args.locale, namespace=args.namespace, key=args.key,
        explain=getattr(args, "explain", False),
        alternatives=getattr(args, "alternatives", False),
        ambiguity=getattr(args, "ambiguity", False),
    )), args)


def run_draft(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_draft(cfg, DraftRequest(
        action=args.action, locale=args.locale or "", namespace=args.namespace or "",
        key=args.key or "", keys=args.keys, by=args.by or "cli",
        mode=args.mode or "", confirm=bool(getattr(args, "confirm", False)),
    )), args)


def run_source_diff(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_source_diff(cfg, args.locale or "", args.namespace or "", args.key or ""), args)


def run_task(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_task(cfg, TaskRequest(
        action=args.action, id=args.id or "", name=args.name or "", namespace=args.namespace,
        keys=args.keys, assign=args.assign, due=args.due or "", unverified=args.unverified,
        assignee=args.assignee or "", by=args.by or "cli",
    )), args)


def run_discuss(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_discuss(cfg, DiscussRequest(
        action=args.action, namespace=args.namespace or "", key=args.key or "",
        text=args.text or "", mention=args.mention or "", open_only=args.open_only,
        by=args.by or "cli",
    )), args)


def run_flag_source(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_flag_source(cfg, FlagSourceRequest(
        namespace=args.namespace, key=args.key, note=args.note,
    )), args)


def run_source_review_queue(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_source_review_queue(cfg, SourceReviewQueueRequest()), args)


def run_bulk_clear(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_bulk_clear(cfg, BulkClearRequest(
        locale=args.locale, locales=args.locales, namespace=args.namespace,
        stale_to_source=args.stale_to_source,
        purge_machine_older_than=args.purge_machine_older_than,
        invalid=args.invalid, latin_leftover=args.latin_leftover,
        dry_run=args.dry_run, confirm=args.confirm,
    )), args)


def run_apply_near(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_apply_near(cfg, ApplyNearRequest(
        locale=args.locale, namespace=args.namespace, key=args.key,
        min_similarity=args.min_similarity, keys=args.keys,
        dry_run=args.dry_run, confirm=args.confirm,
    )), args)


def run_find_replace(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_find_replace(cfg, FindReplaceRequest(
        locale=args.locale, find=args.find, replace=args.replace, namespace=args.namespace,
        case_sensitive=args.case_sensitive, keys=args.keys,
        dry_run=args.dry_run, confirm=args.confirm,
    )), args)


def run_rename_placeholder(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return _print(op_rename_placeholder(cfg, PlaceholderRenameRequest(
        old=args.old, new=args.new, namespace=args.namespace, keys=args.keys,
        dry_run=args.dry_run, confirm=args.confirm,
    )), args)


def run_scan_decide(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    from ..ops.types import request_from_mapping

    # Same request builder as the web handler (M3): CLI dests are the request's field names.
    return _print(op_scan_decide(cfg, request_from_mapping(ScanDecideRequest, vars(args))), args)
