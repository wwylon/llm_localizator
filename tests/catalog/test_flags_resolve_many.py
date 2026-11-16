from __future__ import annotations

import json

from llm_localizator.catalog.flags import FlagStore


def _store(tmp_path, n=4):
    path = tmp_path / "flags.jsonl"
    path.write_text(
        "".join(json.dumps({"locale": "pl", "namespace": "app", "key": f"k{i}"}) + "\n" for i in range(n)),
        encoding="utf-8",
    )
    return FlagStore(path)


def test_resolve_many_removes_all_in_one_pass(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.resolve_many([("pl", "app", "k0"), ("pl", "app", "k2"), ("pl", "app", "zz")]) == 2
    keys = [r["key"] for r in store.rows()]
    assert keys == ["k1", "k3"]


def test_resolve_many_nothing_matches_leaves_file_untouched(tmp_path) -> None:
    store = _store(tmp_path)
    before = store.path.read_bytes()
    assert store.resolve_many([("pl", "app", "nope")]) == 0
    assert store.resolve_many([]) == 0
    assert store.path.read_bytes() == before


def test_resolve_many_updates_identity_cache(tmp_path) -> None:
    store = _store(tmp_path, 2)
    assert not store.append({"locale": "pl", "namespace": "app", "key": "k0"})  # duplicate
    store.resolve_many([("pl", "app", "k0")])
    assert store.append({"locale": "pl", "namespace": "app", "key": "k0"})


def test_resolve_single_still_works(tmp_path) -> None:
    store = _store(tmp_path, 2)
    assert store.resolve("pl", "app", "k1") is True
    assert store.resolve("pl", "app", "k1") is False
