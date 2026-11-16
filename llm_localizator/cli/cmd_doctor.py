"""``llm-localizator doctor`` — environment and project health checks."""

from __future__ import annotations

import argparse
import json

from ..doctor import run_doctor
from ..projects import ConfigError, load_config, resolve
from ..projects.config import discover_config

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = None
    if args.project is not None or args.config is not None:
        cfg = resolve(args.project, args.config)
    else:
        try:
            cfg = load_config(discover_config())
        except ConfigError as exc:
            if "no .llm-localize.toml found" not in str(exc):
                raise

    checks = run_doctor(cfg, web_port=args.port, skip_ollama=args.skip_ollama)

    if args.json:
        print(json.dumps({"checks": [c.to_dict() for c in checks]}, indent=2))
        return 1 if any(c.status == "fail" for c in checks) else 0

    icons = {"ok": "✓", "warn": "!", "fail": "✗"}
    exit_fail = False
    for c in checks:
        if c.status == "fail":
            exit_fail = True
        print(f"  {icons.get(c.status, '?')} {c.name}: {c.detail}")
    return 1 if exit_fail else 0
