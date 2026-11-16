"""Find stray control bytes in source files.

    python scripts/check_control_bytes.py [PATH ...]     # default: llm_localizator tests scripts (*.py)

A backslash escape mangled on its way through a shell heredoc lands in the file as a raw control byte
(``\\b`` becomes 0x08, ``\\f`` 0x0C). The file still parses, so only a test of that exact regex would notice.
Exit 1 and one ``path:line:col 0xNN`` line per byte when any is found; tab, newline and carriage return are allowed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = ("llm_localizator", "tests", "scripts", "experiments")
SUFFIXES = {".py", ".toml", ".js", ".bat"}
SKIP_PARTS = {".venv", "node_modules", "__pycache__", ".git", "clones", ".snapshots", "results", "crawls", "queue"}


BAD = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _walk(base: Path) -> list[Path]:
    """Source files under *base*, never entering skipped folders (``experiments/`` holds large third-party trees)."""
    import os

    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
        out.extend(Path(dirpath) / f for f in filenames if Path(f).suffix in SUFFIXES)
    return sorted(out)


def find(paths: list[Path]) -> list[str]:
    out: list[str] = []
    for base in paths:
        files = [base] if base.is_file() else _walk(base)
        for path in files:
            if not path.is_file() or SKIP_PARTS & set(path.parts):
                continue
            data = path.read_bytes()
            for m in BAD.finditer(data):
                lineno = data.count(b"\n", 0, m.start()) + 1
                col = m.start() - (data.rfind(b"\n", 0, m.start()) + 1) + 1
                name = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
                out.append(f"{name}:{lineno}:{col} 0x{data[m.start()]:02X}")
    return out


def main(argv: list[str]) -> int:
    if argv and argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    paths = [Path(a) for a in argv] or [ROOT / d for d in DEFAULT_DIRS if (ROOT / d).exists()]
    hits = find(paths)
    for hit in hits:
        print(hit)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
