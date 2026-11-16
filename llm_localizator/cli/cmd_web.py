"""``llm-localizator web`` -- serve the local translation browser."""

from __future__ import annotations

import argparse

from ..projects import resolve
from ..web import DEFAULT_MARKETING_PORT, serve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    if getattr(args, "paranoid", False):
        cfg.allow_cloud = False
        cfg.overlay_edit = False
    marketing_port: int | None
    if getattr(args, "no_marketing", False):
        marketing_port = None
    else:
        marketing_port = int(getattr(args, "marketing_port", DEFAULT_MARKETING_PORT))
    return serve(
        cfg,
        port=args.port,
        open_browser=not args.no_browser,
        paranoid=bool(getattr(args, "paranoid", False)),
        marketing_port=marketing_port,
    )
