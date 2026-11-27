"""Regression tests for the Phase 0 audit fixes (security + correctness)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.catalog import io as catalog_io
from llm_localizator.catalog.review_queue import ReviewQueue
from llm_localizator.pipeline.improve import parse_named_keys
from llm_localizator.web.review import list_review_tickets


@pytest.mark.parametrize("bad", ["../x", "..", "a/b", "a\\b", "", ".hidden", "pl/../../etc"])
def test_review_queue_rejects_path_like_locales(tmp_path: Path, bad: str) -> None:
    q = ReviewQueue(tmp_path / "review")
    with pytest.raises(ValueError):
        q.path_for(bad)


@pytest.mark.parametrize("good", ["pl", "pt-BR", "sr_Latn", "zh-Hans"])
def test_review_queue_accepts_real_locales(tmp_path: Path, good: str) -> None:
    q = ReviewQueue(tmp_path / "review")
    assert q.path_for(good) == tmp_path / "review" / f"{good}.jsonl"


def test_web_review_helper_returns_400_style_error_for_traversal() -> None:
    # cfg is never touched: the guard runs first.
    out = list_review_tickets(None, locale="../../x")  # type: ignore[arg-type]
    assert out == {"ok": False, "error": "invalid locale"}


def test_parse_named_keys_dedupes() -> None:
    pairs = parse_named_keys(["app.a,app.a", "app.b", "app.a"], namespaces=["app"])
    assert pairs == [("app", "a"), ("app", "b")]


def test_append_lock_key_stable_across_file_creation(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    before = catalog_io._append_lock_for(p)
    p.write_text("", encoding="utf-8")
    after = catalog_io._append_lock_for(p)
    assert before is after
