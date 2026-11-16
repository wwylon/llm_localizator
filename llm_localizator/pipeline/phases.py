"""Named translation phases (Wave 2 structural seam).

Orchestration still lives in ``translate.py``; this module documents the
phase boundaries and re-exports the stable entry points so callers and
tests can name stages without importing the full engine.
"""

from __future__ import annotations

from .translate import collect_work, run_translation

__all__ = [
    "PHASES",
    "collect_work",
    "run_translation",
]

# collect → retrieve → generate → validate/score → commit → finalize
PHASES = (
    "collect",
    "retrieve",
    "generate",
    "validate_score",
    "commit",
    "finalize",
)
