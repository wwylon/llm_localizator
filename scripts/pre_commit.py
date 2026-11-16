"""Pre-commit checks on the staged files only (M5). Fast: no pytest, no scanner.

    git config core.hooksPath .githooks        # once per clone, opt-in

1. No stray control bytes (a heredoc-mangled ``\\b`` becomes 0x08; see check_control_bytes.py).
2. Every staged ``.py`` file compiles.
3. Nothing staged from the paths the user keeps uncommitted (``web/locales/pl.json``, ``uv.lock`` …) unless
   ``ALLOW_USER_FILES=1`` is set for that commit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_control_bytes import SUFFIXES, find  # noqa: E402

#: Files that hold the user's own uncommitted work; staging them is almost always an accident (``git add <dir>``).
USER_FILES = ("llm_localizator/web/locales/pl.json", "uv.lock")


def staged() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def main() -> int:
    files = staged()
    problems: list[str] = []
    sources = [ROOT / f for f in files if Path(f).suffix in SUFFIXES and (ROOT / f).is_file()]
    problems += find(sources)
    for path in sources:
        if path.suffix == ".py":
            try:
                compile(path.read_bytes(), str(path), "exec")
            except SyntaxError as exc:
                problems.append(f"{path.relative_to(ROOT)}:{exc.lineno}: does not compile: {exc.msg}")
    if os.environ.get("ALLOW_USER_FILES") != "1":
        problems += [f"{f}: staged a file that holds uncommitted user work (ALLOW_USER_FILES=1 to override)"
                     for f in files if f in USER_FILES]
    for line in problems:
        print(line, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
