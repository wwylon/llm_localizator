"""``llm-localizator agent-backlog`` — prompt-ready keys for an AI agent (no LLM)."""

from __future__ import annotations

import argparse
import json

from ..ops.agent_backlog import op_agent_backlog
from ..ops.types import AgentBacklogRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    reasons = None
    raw = getattr(args, "reasons", None)
    if raw:
        reasons = [r.strip() for r in raw.split(",") if r.strip()]
    result = op_agent_backlog(
        cfg,
        AgentBacklogRequest(
            locales=args.locales,
            namespace=args.namespace,
            namespaces=[args.namespace] if args.namespace else None,
            reasons=reasons,
            limit=args.limit,
            fmt=getattr(args, "fmt", "prompt") or "prompt",
            include_existing=bool(getattr(args, "include_existing", False)),
            split=getattr(args, "split", None),
            out_dir=getattr(args, "out_dir", None),
            budget_tokens=getattr(args, "budget_tokens", 15000),
        ),
    )
    if result.exit_code != 0:
        if result.summary:
            print(result.summary)
        return result.exit_code
    if getattr(args, "fmt", "prompt") == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        # Prompt is in lines; print as-is for paste into Cursor.
        print("\n".join(result.lines))
    return result.exit_code
