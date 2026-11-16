from __future__ import annotations

import json

from llm_localizator.catalog import history as hist_mod
from llm_localizator.catalog.history import HistoryStore


def _write(path, n, key="k"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"namespace": "a", "key": key, "i": i}) + "\n" for i in range(n)),
        encoding="utf-8",
    )


def test_compact_skips_rewrite_when_under_retention(tmp_path, monkeypatch) -> None:
    store = HistoryStore(tmp_path, retention=5)
    _write(store.path_for("pl"), 3)
    calls = []
    monkeypatch.setattr(hist_mod, "rewrite_text_locked", lambda *a, **k: calls.append(a))
    store.compact("pl")
    assert calls == []


def test_compact_still_trims_over_retention(tmp_path) -> None:
    store = HistoryStore(tmp_path, retention=2)
    _write(store.path_for("pl"), 5)
    store.compact("pl")
    rows = [json.loads(x) for x in store.path_for("pl").read_text(encoding="utf-8").splitlines()]
    assert [r["i"] for r in rows] == [3, 4]


def test_compact_drops_malformed_lines(tmp_path) -> None:
    store = HistoryStore(tmp_path, retention=5)
    _write(store.path_for("pl"), 2)
    with store.path_for("pl").open("a", encoding="utf-8") as f:
        f.write("not json\n")
    store.compact("pl")
    assert "not json" not in store.path_for("pl").read_text(encoding="utf-8")


def test_compact_preserves_global_chronological_order(tmp_path) -> None:
    store = HistoryStore(tmp_path, retention=2)
    path = store.path_for("pl")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ts": "2026-01-01T00:00:02Z", "namespace": "a", "key": "b", "i": 1},
        {"ts": "2026-01-01T00:00:01Z", "namespace": "a", "key": "a", "i": 0},
        {"ts": "2026-01-01T00:00:04Z", "namespace": "a", "key": "a", "i": 2},
        {"ts": "2026-01-01T00:00:03Z", "namespace": "a", "key": "b", "i": 3},
        {"ts": "2026-01-01T00:00:05Z", "namespace": "a", "key": "a", "i": 4},
        {"ts": "2026-01-01T00:00:06Z", "namespace": "a", "key": "b", "i": 5},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    store.compact("pl")
    kept = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    # retention=2 keeps latest two per key (a:2,4 and b:3,5), then sorts by ts.
    assert [r["i"] for r in kept] == [3, 2, 4, 5]
    assert [r["ts"] for r in kept] == sorted(r["ts"] for r in kept)
