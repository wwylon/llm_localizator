"""The R-009 changed-source bakeoff scores drift without a model (ADR-103)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[2] / "experiments" / "quality_bakeoff"
if not _DIR.is_dir():
    pytest.skip("needs experiments/quality_bakeoff (dev checkout only)", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("source_update_bakeoff", _DIR / "source_update_bakeoff.py")
bake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bake)


def test_corpus_is_self_consistent() -> None:
    data = json.loads(bake.CASES.read_text(encoding="utf-8"))
    for case in data["cases"]:
        assert all(w in case["old_translation"] for w in case["must_keep"]), case["id"]
        assert bake.placeholders_ok(case["old_source"], case["old_translation"]), case["id"]


def test_scoring_counts_kept_words_and_placeholders() -> None:
    case = {"id": "x", "new_source": "Hi {name}", "must_keep": ["Cześć", "{name}"]}
    row = bake.score_case(case, "Cześć {name}", "Witaj")
    assert row["edit_kept"] == 1.0 and row["retranslate_kept"] == 0.0
    assert row["edit_placeholders"] and not row["retranslate_placeholders"]
