"""Shrink ``known_gaps.py`` to the cells that still fail.

    python -m tests.scan.matrix.update_known_gaps

Refuses to add a cell: a new failure is a regression to fix, not a gap to record.
"""

from __future__ import annotations

from pathlib import Path

from .known_gaps import KNOWN_GAPS
from .runner import run_language
from .spec import LANGS


def main() -> int:
    failing = {(lang, cat) for lang in LANGS for cat, cell in run_language(lang).items() if not cell["ok"]}
    new = failing - KNOWN_GAPS
    if new:
        print(f"REGRESSION: new failing cells {sorted(new)}")
        return 1
    path = Path(__file__).with_name("known_gaps.py")
    head = path.read_text(encoding="utf-8").split("KNOWN_GAPS: set")[0]
    rows = ",\n".join(f'    ("{lang}", "{cat}")' for lang, cat in sorted(failing))
    path.write_text(f"{head}KNOWN_GAPS: set[tuple[str, str]] = {{\n{rows}{',' if rows else ''}\n}}\n", encoding="utf-8")
    print(f"{len(failing)} gaps left (was {len(KNOWN_GAPS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
