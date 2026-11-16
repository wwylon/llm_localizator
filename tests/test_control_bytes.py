"""No stray control bytes in source (a heredoc-mangled ``\\b`` becomes 0x08 and still parses)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_control_bytes", ROOT / "scripts" / "check_control_bytes.py")
ccb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccb)


def test_repo_sources_have_no_control_bytes() -> None:
    assert ccb.find([ROOT / d for d in ccb.DEFAULT_DIRS]) == []


def test_detects_backspace_in_regex(tmp_path: Path) -> None:
    bad = tmp_path / "m.py"
    bad.write_bytes(b'import re\nWORD = re.compile(r"\x08word\x08")\n')
    hits = ccb.find([tmp_path])
    assert len(hits) == 2 and hits[0].endswith(":2:21 0x08")
