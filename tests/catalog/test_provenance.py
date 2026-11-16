"""ADR-19 provider provenance."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.catalog.history import HistoryStore, make_history_event
from llm_localizator.catalog.provenance import (
    infer_provider,
    normalize_provider,
    provider_of,
)
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.state import StateStore, make_entry
from llm_localizator.pipeline.recording import record_candidate


def test_normalize_provider():
    assert normalize_provider(None) == "ollama"
    assert normalize_provider("null") == "ollama"
    assert normalize_provider("anthropic") == "anthropic"
    assert normalize_provider("ctranslate2") == "ctranslate2"


def test_infer_provider_rules():
    assert infer_provider(model="human") == "human"
    assert infer_provider(model="aya-expanse:8b") == "ollama"
    assert infer_provider(model="claude-haiku-4-5") == "anthropic"
    assert infer_provider(model="gpt-5.6-luna") == "openai"
    assert infer_provider(model="deepseek-flash") == "deepseek"
    assert infer_provider(model="deepl") == "deepl"
    assert infer_provider(model="human", verified_by="cursor-agent") == "agent"
    assert infer_provider({"model": "llama3.2", "status": "machine"}) == "ollama"
    # Do not invent agent without verified_by cue.
    assert infer_provider(model="human", status="human") == "human"


def test_make_entry_stamps_provider():
    entry = make_entry("Hello", "aya-expanse:8b", provider="ollama")
    assert entry["provider"] == "ollama"
    assert entry["model"] == "aya-expanse:8b"
    legacy_shape = make_entry("Hello", "m")
    assert legacy_shape["provider"] == "ollama"


def test_record_candidate_writes_provider(tmp_path: Path):
    state = StateStore(tmp_path / "state")
    scores = ScoreStore(tmp_path / "scores")
    history = HistoryStore(tmp_path / "history")
    entry = record_candidate(
        state=state, scores=scores, history=history,
        locale="pl", namespace="app", key="greet",
        source="Hello", previous=None, text="Cześć",
        model="aya-expanse:8b", quality_score=0.9,
        quality_signals=[], trigger="translate",
        provider="ollama",
    )
    assert entry["provider"] == "ollama"
    events = history.events_for("pl", "app", "greet")
    assert len(events) == 1
    assert events[0].provider == "ollama"


def test_history_reads_legacy_jsonl_without_provider(tmp_path: Path):
    path = tmp_path / "pl.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "ts": "2026-01-01T00:00:00Z",
        "namespace": "app",
        "key": "greet",
        "prev": None,
        "next": "Cześć",
        "model": "m",
        "status": "machine",
        "src_sha": "abc",
        "trigger": "translate",
        "quality_score": 0.5,
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    store = HistoryStore(tmp_path)
    events = store.events_for("pl", "app", "greet")
    assert len(events) == 1
    assert events[0].provider is None
    assert events[0].model == "m"


def test_provider_of_prefers_stamped():
    assert provider_of({"provider": "agent", "model": "human"}) == "agent"
    assert provider_of({"model": "claude-sonnet"}) == "anthropic"


def test_make_history_event_normalizes():
    ev = make_history_event(
        namespace="app", key="k", prev=None, next_text="x",
        model="m", status="machine", src_sha="a", trigger="t",
        provider="null",
    )
    assert ev.provider == "ollama"
