"""B5: the weekly bench fails on a recall drop."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "experiments" / "scanner_bench").is_dir():
    pytest.skip("needs experiments/scanner_bench (dev checkout only)", allow_module_level=True)


def _weekly():
    spec = importlib.util.spec_from_file_location("weekly", ROOT / "experiments/scanner_bench/weekly.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_regression_gate() -> None:
    w = _weekly()
    base = {"recall": 0.74, "precision": 0.82, "visible": 0.68}
    assert w.regressions(base, base) == []
    assert w.regressions(base, {**base, "precision": 0.805}) == []
    assert w.regressions(base, {**base, "recall": 0.72}) == ["recall 0.740 -> 0.720"]
    assert w.regressions(base, {**base, "visible": None}) == []
