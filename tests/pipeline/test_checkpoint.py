"""Shared flush_pending / accept_allowed helpers."""

from __future__ import annotations

import pytest

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.catalog.history import HistoryStore
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.state import now_iso
from llm_localizator.pipeline.checkpoint import accept_allowed, flush_pending
from llm_localizator.pipeline.recording import record_candidate

from ..conftest import write_json


def test_accept_allowed_blocks_verified() -> None:
    entry = make_entry("Hello", "m")
    entry["verified_at"] = now_iso()
    assert accept_allowed("Hello", entry) is False
    assert accept_allowed("Hello", entry, force=True) is True
    assert accept_allowed("Hello", entry, allow_current=True) is False


def test_accept_allowed_flagged_allows_current() -> None:
    entry = make_entry("Hello", "m")
    assert accept_allowed("Hello", entry) is False  # already current
    assert accept_allowed("Hello", entry, allow_current=True) is True


def test_flush_pending_writes_history(
    tmp_path, make_config, make_catalog,
) -> None:
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {})
    cfg = make_config(tmp_path)
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_root())
    scores = ScoreStore(cfg.scores_root())
    history = HistoryStore(cfg.history_root())
    pending: dict = {}
    pending_history: list = []
    record_candidate(
        state=state, scores=scores, history=history,
        locale="pl", namespace="app", key="greet",
        source="Hello", previous=None, text="Cześć",
        model="test", quality_score=1.0, quality_signals=[],
        trigger="translate", pending_history=pending_history,
    )
    pending[("app", "pl")] = {"greet": "Cześć"}
    flushed = flush_pending(
        cfg, catalog, state, scores, pending, history, pending_history,
    )
    assert flushed.flushed == [("pl", "app", "greet")]
    assert flushed.skipped_external == []
    assert catalog.load("pl", "app")["greet"] == "Cześć"
    assert history.events_for("pl", "app", "greet")


def test_flush_pending_skips_keys_edited_since_pick(
    tmp_path, make_config, make_catalog,
) -> None:
    """Second guard: catalogue changed after pick → keep disk, skip our write."""
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello", "bye": "Bye"})
    write_json(
        tmp_path / "messages" / "pl" / "app.json",
        {"greet": "Stare", "bye": "Pa"},
    )
    cfg = make_config(tmp_path)
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_root())
    scores = ScoreStore(cfg.scores_root())
    history = HistoryStore(cfg.history_root())
    pending: dict = {("app", "pl"): {"greet": "Cześć", "bye": "Do widzenia"}}
    baselines: dict = {("app", "pl"): {"greet": "Stare", "bye": "Pa"}}
    pending_history: list = []
    record_candidate(
        state=state, scores=scores, history=history,
        locale="pl", namespace="app", key="greet",
        source="Hello", previous="Stare", text="Cześć",
        model="test", quality_score=1.0, quality_signals=[],
        trigger="translate", pending_history=pending_history,
    )
    record_candidate(
        state=state, scores=scores, history=history,
        locale="pl", namespace="app", key="bye",
        source="Bye", previous="Pa", text="Do widzenia",
        model="test", quality_score=1.0, quality_signals=[],
        trigger="translate", pending_history=pending_history,
    )
    # Out-of-band edit while the run holds a pending write for greet.
    write_json(
        tmp_path / "messages" / "pl" / "app.json",
        {"greet": "Ręczna", "bye": "Pa"},
    )
    catalog.invalidate()
    outcome = flush_pending(
        cfg, catalog, state, scores, pending, history, pending_history,
        baselines=baselines, use_journal=False,
    )
    assert outcome.skipped_external == [("pl", "app", "greet")]
    assert outcome.flushed == [("pl", "app", "bye")]
    data = catalog.load("pl", "app")
    assert data["greet"] == "Ręczna"
    assert data["bye"] == "Do widzenia"
    assert not history.events_for("pl", "app", "greet")
    assert history.events_for("pl", "app", "bye")


def test_flush_pending_keeps_unwritten_history_on_append_failure(
    tmp_path, make_config, make_catalog, monkeypatch,
) -> None:
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {})
    cfg = make_config(tmp_path)
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_root())
    scores = ScoreStore(cfg.scores_root())
    history = HistoryStore(cfg.history_root())
    pending: dict = {}
    pending_history: list = []
    record_candidate(
        state=state, scores=scores, history=history,
        locale="pl", namespace="app", key="greet",
        source="Hello", previous=None, text="Cześć",
        model="test", quality_score=1.0, quality_signals=[],
        trigger="translate", pending_history=pending_history,
    )
    pending[("app", "pl")] = {"greet": "Cześć"}
    real_append = history.append
    calls = {"n": 0}

    def boom(locale, event):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real_append(locale, event)

    monkeypatch.setattr(history, "append", boom)
    with pytest.raises(OSError, match="disk full"):
        flush_pending(
            cfg, catalog, state, scores, pending, history, pending_history,
            use_journal=False,
        )
    assert len(pending_history) == 1
    assert catalog.load("pl", "app")["greet"] == "Cześć"
