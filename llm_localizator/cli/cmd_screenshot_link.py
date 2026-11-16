"""``screenshot-link``: attach screenshots to keys (C-012, ADR-102)."""

from __future__ import annotations

import argparse
import json
import sys

from ..ops.screenshot_link import op_screenshot_link
from ..ops.types import ScreenshotLinkRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    # `cmd link` parses `link` as the optional project positional; treat it as the action.
    if args.project in ("list", "link", "unlink") and args.action == ("list", "link", "unlink")[0]:
        args.action, args.project = args.project, None
    result = op_screenshot_link(resolve(args.project, args.config), ScreenshotLinkRequest(
        action=args.action, file=args.file or "", namespace=args.namespace or "", key=args.key or "",
        region=args.region, note=args.note or "", link=args.link or "",
    ))
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
        return result.exit_code
    if not result.ok:
        print(result.summary, file=sys.stderr)
        return result.exit_code
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code
