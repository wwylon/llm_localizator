"""Concurrent first loads of the dashboard stats compute them once."""

from __future__ import annotations

import threading

from llm_localizator.web import dashboard


def test_overview_stats_is_single_flight(monkeypatch) -> None:
    calls: list[int] = []
    gate = threading.Event()

    class St:
        _overview_stats_cache = None
        stats_lock = threading.Lock()

    st = St()

    def compute(state):
        calls.append(1)
        gate.wait(1)
        state._overview_stats_cache = {"locales": []}
        return state._overview_stats_cache

    monkeypatch.setattr(dashboard, "_compute_overview_stats", compute)
    out: list[dict] = []
    ts = [threading.Thread(target=lambda: out.append(dashboard.overview_stats(st))) for _ in range(5)]
    for t in ts:
        t.start()
    gate.set()
    for t in ts:
        t.join()
    assert len(calls) == 1 and len(out) == 5
