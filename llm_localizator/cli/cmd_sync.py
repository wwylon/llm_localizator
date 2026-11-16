"""``llm-localizator sync`` / ``run-sync`` — gather backlog (queue chains translate)."""

from __future__ import annotations

import argparse

from ..catalog import catalog_for
from ..pipeline.sync import run_sync
from ..projects import resolve
from ..projects.taskqueue import TaskqueueNotFound, submit

__all__ = ["run_submit", "run_execute"]


def run_submit(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    overrides: dict[str, str] = {}
    locales = list(getattr(args, "locales", None) or cfg.active_targets())
    if locales:
        overrides["--locales"] = ",".join(locales)
    if getattr(args, "dry_run", False):
        overrides["--dry-run"] = "true"
    # Blueprint already passes --no-translate; keep override for hand retries.
    if getattr(args, "no_translate", False):
        overrides["--no-translate"] = "true"
    for flag in ("strict_branch", "diff", "exit_nonzero"):
        if getattr(args, flag, False):
            overrides[f"--{flag.replace('_', '-')}"] = "true"
    try:
        return submit(cfg, "sync", overrides).exit_code
    except TaskqueueNotFound as exc:
        print(f"error: {exc}")
        return 1


def run_execute(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    catalog = catalog_for(cfg)
    # Default gather-only. Opt in to in-process enqueue with --submit-translate
    # (discouraged when the task is already under taskqueue — use on_complete).
    submit_translate = bool(getattr(args, "submit_translate", False)) and not args.dry_run
    if getattr(args, "no_translate", False):
        submit_translate = False
    result = run_sync(
        cfg,
        catalog,
        locales=args.locales,
        dry_run=args.dry_run,
        submit_translate=submit_translate,
        strict_branch=bool(getattr(args, "strict_branch", False)),
        diff=bool(getattr(args, "diff", False)),
        exit_nonzero=bool(getattr(args, "exit_nonzero", False)),
    )
    return result.exit_code
