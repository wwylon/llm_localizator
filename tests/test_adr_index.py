"""Every ADR file has a row in plan/decisions/README.md and every row points at a file (M5)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

if not (Path(__file__).resolve().parents[1] / "plan" / "decisions").is_dir():
    pytest.skip("needs plan/decisions (private checkout only)", allow_module_level=True)

_SPEC = importlib.util.spec_from_file_location(
    "adr_index", Path(__file__).resolve().parents[1] / "scripts" / "adr_index.py")
adr_index = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(adr_index)


def test_adr_index_is_complete() -> None:
    missing, dangling = adr_index.problems()
    assert not missing, f"ADR files without a README row (run scripts/adr_index.py --fix): {missing}"
    assert not dangling, f"README rows pointing at missing files: {dangling}"
