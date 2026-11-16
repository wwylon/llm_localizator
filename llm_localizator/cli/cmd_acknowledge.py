"""``llm-localizator acknowledge-flush`` — delete a leftover flush journal."""

from __future__ import annotations

import argparse

from ..ops.acknowledge import op_acknowledge_flush
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    result = op_acknowledge_flush(cfg)
    print(result.summary)
    return result.exit_code
