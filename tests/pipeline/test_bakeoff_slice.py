"""Bakeoff --slice disambiguation (ADR-159)."""

from __future__ import annotations

import pytest

from llm_localizator.pipeline.bakeoff import (
    BAKEOFF_SLICES,
    load_slice,
    stratify,
)


def test_disambiguation_slice_has_short_ui_rows() -> None:
    rows = load_slice("disambiguation")
    assert len(rows) >= 20
    assert all(len(r.source.split()) <= 2 for r in rows)
    assert any("sense:" in (r.context or "") for r in rows)
    picked = stratify(rows, 10, seed=1)
    assert len(picked) == 10


def test_unknown_slice_raises() -> None:
    with pytest.raises(ValueError, match="unknown bakeoff slice"):
        load_slice("nope")
    assert "disambiguation" in BAKEOFF_SLICES
