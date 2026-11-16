"""ScoreStore.top_peers reads the score table once, not once per key."""

import pytest

from llm_localizator.catalog.scores import ScoreStore


def test_top_peers_loads_the_table_once(tmp_path, monkeypatch) -> None:
    store = ScoreStore(tmp_path)
    source = {f"k{i}": f"Source text {i}" for i in range(50)}
    target = {k: f"Cel {k}" for k in source}
    for k in source:
        store.record("pl", "app", k, score=0.95, signals=[], text=target[k])
    store.save("pl")

    calls: list[str] = []
    real = store.load
    monkeypatch.setattr(store, "load", lambda loc: calls.append(loc) or real(loc))
    peers = store.top_peers("pl", "app", catalog_source=source, catalog_target=target,
                            exclude_key="k0", limit=3)
    assert len(peers) == 3
    assert len(calls) == 1


def test_corrupt_scores_json_raises(tmp_path) -> None:
    path = tmp_path / "pl.json"
    path.write_text("{not valid", encoding="utf-8")
    store = ScoreStore(tmp_path)
    with pytest.raises(ValueError, match="not valid JSON"):
        store.load("pl")
