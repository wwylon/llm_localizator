"""Process metrics from history: edit rate, cycle time, coverage trend (ADR-52)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from llm_localizator.catalog.history import HistoryStore, make_history_event
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.metrics import op_metrics
from llm_localizator.ops.types import MetricsRequest
from llm_localizator.pipeline.metrics import compute_locale_metrics, parse_since

from ..conftest import setup_project

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _event(key, trigger, hours_ago, *, status="machine", provider="ollama"):
    event = make_history_event(
        namespace="app", key=key, prev=None, next_text="x", model="m", status=status,
        src_sha="s", trigger=trigger, provider=provider,
    )
    event.ts = (NOW - timedelta(hours=hours_ago)).isoformat()
    return event


EVENTS = [
    _event("a", "translate", 30),
    _event("a", "web-edit", 6, status="human", provider="human"),  # edited 24h later
    _event("b", "translate", 20),
    _event("b", "web-edit", 8, status="human", provider="human"),  # edited 12h later
    _event("c", "translate", 10),  # never edited
    _event("d", "translate", 10),
    _event("d", "agent-edit", 2, status="agent", provider="agent"),  # an agent is not a person
    _event("e", "web-edit", 5, status="human", provider="human"),  # human-only key, no machine
]


def test_edit_rate_and_cycle_time() -> None:
    out = compute_locale_metrics("pl", EVENTS, total_keys=10, now=NOW).to_dict()
    assert (out["machineKeys"], out["editedKeys"], out["editRate"]) == (4, 2, 0.5)
    assert out["cycleHoursMean"] == 18.0 and out["cycleHoursMedian"] == 18.0


def test_since_limits_the_machine_events_considered() -> None:
    out = compute_locale_metrics(
        "pl", EVENTS, total_keys=10, now=NOW, since=NOW - timedelta(hours=15),
    )
    assert (out.machine_keys, out.edited_keys) == (2, 0)  # only c and d were translated in window


def test_no_machine_translations_gives_no_rate() -> None:
    assert compute_locale_metrics("pl", [], total_keys=5, now=NOW).edit_rate is None


def test_coverage_trend_is_cumulative_and_capped() -> None:
    old = _event("a", "translate", 24 * 20)
    recent = _event("b", "translate", 5)
    trend = compute_locale_metrics("pl", [old, recent], total_keys=2, now=NOW).coverage
    assert trend[0]["coverage"] == 0.0 and trend[-1]["coverage"] == 1.0
    assert [p["coverage"] for p in trend] == sorted(p["coverage"] for p in trend)
    assert compute_locale_metrics("pl", [old], total_keys=0, now=NOW).coverage == []


def test_parse_since() -> None:
    assert parse_since("30d", NOW) == NOW - timedelta(days=30)
    assert parse_since("2w", NOW) == NOW - timedelta(weeks=2)
    assert parse_since("2026-09-01", NOW).date().isoformat() == "2026-09-01"
    assert parse_since(None, NOW) is None
    with pytest.raises(ValueError):
        parse_since("soon", NOW)


def test_op_reads_history_files(project_root, make_config) -> None:
    setup_project(project_root, {"a": "Save", "b": "Cancel"})
    cfg = make_config(project_root)
    store = HistoryStore(cfg.history_root())
    for event in EVENTS[:4]:
        store.append("pl", event)
    result = op_metrics(cfg, MetricsRequest())
    row = result.data["locales"][0]
    assert result.ok and row["locale"] == "pl" and row["machineKeys"] == 2
    assert row["editRate"] == 1.0
    assert "edit rate" in result.lines[0] and "100.0%" in result.lines[1]

    bad = op_metrics(cfg, MetricsRequest(since="soon"))
    assert not bad.ok and "--since" in bad.summary
    assert dispatch_op(cfg, "metrics", {"since": "90d"}, actor_role="Admin")["ok"] is True


def test_weekly_edit_rate_series() -> None:
    m = compute_locale_metrics("pl", EVENTS, total_keys=5, now=NOW).to_dict()
    weekly = m["editRateWeekly"]
    assert len(weekly) == 12 and weekly[-1]["weekEnding"] == NOW.date().isoformat()
    last = weekly[-1]
    assert last["machineKeys"] == 4  # a, b, c, d were machine-translated this week
    assert last["editRate"] == 0.5  # a and b were edited
    assert weekly[0]["editRate"] is None  # no machine keys that week
