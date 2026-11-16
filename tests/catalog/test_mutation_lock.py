"""Cross-process mutation lock tests."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from llm_localizator.catalog.history import HistoryStore
from llm_localizator.catalog.mutation_lock import MutationLockTimeout, mutation_lock
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.state import StateStore
from llm_localizator.pipeline.recording import record_candidate
from llm_localizator.pipeline.translate import _flush, run_translation
from llm_localizator.providers import NullProvider

from ..conftest import write_json


def test_mutation_lock_serializes_writers(tmp_path: Path) -> None:
    lock_path = tmp_path / ".mutation.lock"
    order: list[str] = []
    with mutation_lock(lock_path, timeout_s=2):
        order.append("a")
    with mutation_lock(lock_path, timeout_s=2):
        order.append("b")
    assert order == ["a", "b"]


def test_mutation_lock_timeout(tmp_path: Path) -> None:
    lock_path = tmp_path / ".mutation.lock"
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with mutation_lock(lock_path, timeout_s=5):
            held.set()
            release.wait(timeout=5)

    t = threading.Thread(target=holder)
    t.start()
    assert held.wait(timeout=2)
    with pytest.raises(MutationLockTimeout):
        with mutation_lock(lock_path, timeout_s=0.2):
            pass
    release.set()
    t.join(timeout=2)


def test_pending_history_lands_only_on_flush(tmp_path: Path, make_config, make_catalog) -> None:
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
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
    assert not (cfg.history_root() / "pl.jsonl").exists()
    _flush(cfg, catalog, state, scores, pending, history, pending_history)
    assert (cfg.history_root() / "pl.jsonl").exists()
    assert catalog.load("pl", "app")["greet"] == "Cześć"
    assert history.events_for("pl", "app", "greet")


def test_translate_writes_history_with_catalog(
    project_root, make_config, make_catalog, silent,
) -> None:
    write_json(project_root / "messages" / "en" / "app.json", {"greet": "Hello"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    run_translation(cfg, catalog, NullProvider(), report=silent)
    assert catalog.load("pl", "app")["greet"]
    events = HistoryStore(cfg.history_root()).events_for("pl", "app", "greet")
    assert len(events) == 1


def test_tm_only_flush_writes_pending_history(
    tmp_path: Path, make_config, make_catalog,
) -> None:
    """TM-only early _flush must pass history (ADR-24); not catalog-only."""
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
        model="tm-model", quality_score=1.0, quality_signals=["tm exact hit"],
        trigger="tm-hit", provider="import", scorer="tm",
        pending_history=pending_history,
    )
    pending[("app", "pl")] = {"greet": "Cześć"}
    # Same signature as the TM-only early exit in translate.py.
    _flush(cfg, catalog, state, scores, pending, history, pending_history)
    assert pending == {}
    assert pending_history == []
    events = history.events_for("pl", "app", "greet")
    assert len(events) == 1
    assert events[0].trigger == "tm-hit"
