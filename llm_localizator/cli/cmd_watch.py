"""``llm-localizator watch`` — foreground re-sync on source changes (not a daemon)."""

from __future__ import annotations

import argparse

from ..ops.watch import run_watch
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    return run_watch(cfg, interval=max(0.5, float(args.interval)), diff=bool(args.diff))
