"""``llm-localizator quality`` -- one-shot quality report, no registration needed."""

from __future__ import annotations

import argparse
import json

from ..ops.quality import op_quality
from ..ops.types import QualityRequest
from ..projects import resolve

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    adhoc = bool(args.path_template)
    cfg = None if adhoc else resolve(args.project, args.config)
    result = op_quality(cfg, QualityRequest(
        root=args.root,
        fmt=args.catalog_format,
        path_template=args.path_template,
        source=args.source,
        targets=args.targets,
        locales=args.locales,
        score=args.score,
        model=args.model,
        limit=args.limit,
    ))
    if args.fmt == "json":
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    else:
        for line in result.lines or [result.summary]:
            print(line)
    return result.exit_code
