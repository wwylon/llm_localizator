"""Scores store a digest of the scored text; legacy rows still match."""

from __future__ import annotations

from llm_localizator.catalog.scores import ScoreStore, score_matches_text


def test_record_stores_a_digest_not_the_text(tmp_path):
    store = ScoreStore(tmp_path)
    store.record("pl", "app", "k", score=0.9, signals=[], text="Czesc")
    row = store.get("pl", "app", "k")
    assert "text" not in row and row["text_sha"]
    assert score_matches_text(row, "Czesc")
    assert not score_matches_text(row, "Cześć")


def test_legacy_rows_with_text_still_match():
    assert score_matches_text({"text": "abc"}, "abc")
    assert not score_matches_text({"text": "abc"}, "abd")
    assert not score_matches_text({}, "abd")
