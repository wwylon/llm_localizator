"""``llm-localizator check`` -- CI gate: non-zero when translations are stale or missing."""

from __future__ import annotations

import argparse
import json
import sys

from ..ops.status import op_status
from ..ops.types import StatusRequest
from ..projects import resolve

__all__ = ["run", "evaluate"]


def evaluate(rows: list[dict], *, min_coverage: float, allow_stale: bool) -> list[str]:
    """Human-readable problems; empty means the gate passes. Frozen locales are skipped."""
    problems: list[str] = []
    for row in rows:
        if row.get("frozen"):
            continue
        locale = row["locale"]
        coverage = float(row.get("coverage") or 0.0)
        if coverage < min_coverage:
            problems.append(
                f"{locale}: coverage {coverage:.1%} is below {min_coverage:.1%} "
                f"({row.get('missing', 0)} missing)"
            )
        if row.get("stale") and not allow_stale:
            problems.append(f"{locale}: {row['stale']} stale translation(s)")
    return problems


def github_annotation(message: str) -> str:
    """One GitHub Actions error annotation (``::error``) for a check problem; newlines and ``%`` are escaped."""
    text = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error title=llm-localizator check::{text}"


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_status(cfg, StatusRequest())
    if not result.ok:
        print(result.summary or "status failed", file=sys.stderr)
        return result.exit_code
    rows = result.data.get("locales", [])
    wanted = {x.strip() for x in (args.locales or "").split(",") if x.strip()}
    if wanted:
        rows = [r for r in rows if r["locale"] in wanted]
    problems = evaluate(rows, min_coverage=args.min_coverage, allow_stale=args.allow_stale)
    if args.fmt == "json":
        print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
    elif args.fmt == "github":
        for line in problems:
            print(github_annotation(line))
        if not problems:
            print(f"{cfg.name}: {len(rows)} locale(s) up to date")
    elif problems:
        for line in problems:
            print(line, file=sys.stderr)
    else:
        print(f"{cfg.name}: {len(rows)} locale(s) up to date")
    return 1 if problems else 0
