"""``llm-localizator agent-hardcoded`` — paste-ready source report (no rewrite)."""

from __future__ import annotations

import argparse
import json

from ..ops.agent_hardcoded import op_agent_hardcoded
from ..ops.types import AgentHardcodedRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    if getattr(args, "status", False):
        from ..ops.agent_hardcoded import scan_cache_status

        print(json.dumps(scan_cache_status(cfg), indent=2, ensure_ascii=False))
        return 0
    llm = bool(getattr(args, "llm", False))
    dry = bool(getattr(args, "dry_run", False))
    submit = False
    if llm and not dry and args.command == "agent-hardcoded":
        from ..projects.taskqueue import tq_available

        submit = tq_available()
    result = op_agent_hardcoded(
        cfg,
        AgentHardcodedRequest(
            adapter=getattr(args, "adapter", None),
            limit=getattr(args, "limit", None),
            fmt=getattr(args, "fmt", "prompt") or "prompt",
            llm=llm,
            dry_run=dry,
            submit=submit,
            catalogue_audit=getattr(args, "catalogue_audit", True),
            refresh=getattr(args, "refresh", False),
            show_ignored=getattr(args, "show_ignored", False),
            show_low=getattr(args, "show_low", False),
            split=getattr(args, "split", None),
            budget_tokens=getattr(args, "budget_tokens", 15000),
            max_hits=getattr(args, "max_hits", 150),
            out_dir=getattr(args, "out_dir", None),
        ),
    )
    if result.exit_code != 0:
        if result.summary:
            print(result.summary)
        return result.exit_code
    if getattr(args, "fmt", "prompt") == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        print("\n".join(result.lines))
    return result.exit_code
