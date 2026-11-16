"""``llm-localizator migrate-state`` -- rewrite derived fields in state files.

Needed when :data:`llm_localizator.core.hash.SIGNATURE_VERSION` changes.
"""

from __future__ import annotations

import argparse

from ..ops.migrate import op_migrate
from ..ops.types import MigrateRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_migrate(cfg, MigrateRequest(
        locales=args.locales,
        dry_run=args.dry_run,
        stamp_provider=bool(getattr(args, "stamp_provider", False)),
    ))
    for line in result.lines:
        print(line)
    return result.exit_code
