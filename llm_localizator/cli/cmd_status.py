"""``llm-localizator status`` -- per-locale coverage from state files, no LLM."""

from __future__ import annotations

import argparse
import json
import sys

from ..ops.status import LocaleStatus, collect, collect_missing, op_status
from ..ops.types import StatusRequest
from ..projects import resolve

__all__ = ["run", "LocaleStatus", "collect", "collect_missing"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_status(cfg, StatusRequest(
        missing=getattr(args, "missing", False),
        collection=getattr(args, "collection", None),
        by_screen=getattr(args, "by_screen", False),
    ))

    if args.fmt == "json":
        print(json.dumps(result.data, indent=2))
        return result.exit_code

    if not result.ok or result.data.get("kind") == "remote" or getattr(args, "missing", False):
        if not result.ok and result.summary:
            print(result.summary, file=sys.stderr)
        for line in result.lines:
            print(line)
        return result.exit_code

    rows = result.data.get("locales", [])
    print(f"{cfg.name}: {len(rows)} target locale(s)\n")
    print(f"{'locale':<8} {'coverage':>9} {'done':>7} {'stale':>7} {'missing':>8}  notes")
    for row in rows:
        note = ""
        if row.get("namespaces_missing"):
            note = f"{row['namespaces_missing']} namespace file(s) absent"
        if row.get("total") and row.get("translated") == 0:
            note = ("never translated" + (f"; {note}" if note else ""))
        cov = row.get("coverage", 0.0)
        print(
            f"{row['locale']:<8} {cov:>8.1%} {row.get('translated', 0):>7} "
            f"{row.get('stale', 0):>7} {row.get('missing', 0):>8}  {note}"
        )
        print(
            "         leverage: "
            f"tm={row.get('tm_reused', 0)} llm={row.get('llm_generated', 0)} "
            f"human={row.get('human_edited', 0)} agent={row.get('agent_edited', 0)} "
            f"imported={row.get('imported', 0)}"
        )
    return result.exit_code
