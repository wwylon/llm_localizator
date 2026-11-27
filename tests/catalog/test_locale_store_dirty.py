"""Saving an unchanged locale store does not rewrite the file."""

from __future__ import annotations

import json
import os
import time

from llm_localizator.catalog import io as cio
from llm_localizator.catalog._locale_json_store import LocaleJsonStore


def _touch_newer(path) -> None:
    """Bump mtime past the cached value (Windows often keeps the same ns)."""
    try:
        older = path.stat().st_mtime_ns
    except OSError:
        older = 0
    newer = max(older + 1_000_000_000, time.time_ns())
    os.utime(path, ns=(newer, newer))


def test_unchanged_save_skips_the_write(tmp_path, monkeypatch) -> None:
    store = LocaleJsonStore(tmp_path)
    store.load("pl")["a"] = 1
    store.save("pl")
    writes: list[str] = []
    real = cio.atomic_write_text
    monkeypatch.setattr(
        "llm_localizator.catalog._locale_json_store.atomic_write_text",
        lambda p, t: (writes.append(str(p)) if not str(p).endswith(".sha256") else None, real(p, t)),
    )
    store.save("pl")
    assert writes == []
    store.load("pl")["b"] = 2
    store.save("pl")
    assert len(writes) == 1
    # An external edit forces the next save to write again.
    (tmp_path / "pl.json").write_text('{"x": 1}', encoding="utf-8")
    store.load("pl")
    store.save("pl")
    assert len(writes) == 2


def test_external_edit_merges_without_deepcopy_base(tmp_path) -> None:
    """Three-way merge still keeps our edits and theirs (base is JSON text).

    Simulates the race ``save`` guards against: cache mtime lags disk because
    another writer landed between ``load`` and ``_merge_external``.
    """
    path = tmp_path / "pl.json"
    path.write_text(json.dumps({"keep": 1, "mine": 1, "theirs": 1}), encoding="utf-8")
    store = LocaleJsonStore(tmp_path)
    data = store.load("pl")
    data["mine"] = 2
    del data["theirs"]
    # Disk advances while our cache still points at the pre-edit mtime.
    path.write_text(
        json.dumps({"keep": 1, "mine": 1, "theirs": 9, "added": 3}, indent=2) + "\n",
        encoding="utf-8",
    )
    _touch_newer(path)
    merged = store._merge_external("pl", data)
    assert merged["mine"] == 2
    # Our delete of ``theirs`` wins over their in-place edit (existing merge rule).
    assert "theirs" not in merged
    assert merged["added"] == 3
    assert merged["keep"] == 1


def test_load_keeps_base_as_text_not_a_second_dict(tmp_path) -> None:
    path = tmp_path / "pl.json"
    path.write_text(json.dumps({"a": {"n": 1}}), encoding="utf-8")
    store = LocaleJsonStore(tmp_path)
    store.load("pl")
    assert "pl" in store._base_text
    assert not hasattr(store, "_base") or "pl" not in getattr(store, "_base", {})


def test_merge_refuses_corrupt_disk(tmp_path) -> None:
    """Corrupt on-disk JSON must not be overwritten by a stale in-memory copy."""
    import pytest

    path = tmp_path / "pl.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    store = LocaleJsonStore(tmp_path)
    data = store.load("pl")
    data["a"] = 2
    path.write_text("{not-json", encoding="utf-8")
    _touch_newer(path)
    with pytest.raises(ValueError, match="disk JSON unreadable"):
        store._merge_external("pl", data)
    assert path.read_text(encoding="utf-8") == "{not-json"
