"""Plan-review-7 phase 5 (web): cache order, LRU eviction, threshold on has_findings."""

from __future__ import annotations

from collections import OrderedDict

import llm_localizator.web.server as srv
from llm_localizator.web import build_state

from .conftest import setup_project


def _state(tmp_path, make_config, source=None, existing=None):
    setup_project(
        tmp_path, source or {"a": "A", "b": "B"}, existing=existing or {"a": "x", "b": "y"},
    )
    return build_state(make_config(tmp_path))


def test_findings_cache_hit_skips_source_total(tmp_path, make_config, monkeypatch) -> None:
    st = _state(tmp_path, make_config)
    srv.findings(st, "pl", "app")
    calls = []
    real = srv._source_total
    monkeypatch.setattr(srv, "_source_total", lambda s: calls.append(1) or real(s))
    srv.findings(st, "pl", "app")
    assert calls == []


def test_source_total_is_cached_until_invalidated(tmp_path, make_config, monkeypatch) -> None:
    st = _state(tmp_path, make_config)
    first = srv._source_total(st)
    loads = []
    real = st.catalog.load
    monkeypatch.setattr(st.catalog, "load", lambda *a, **k: loads.append(a) or real(*a, **k))
    assert srv._source_total(st) == first
    assert loads == []
    srv.invalidate_caches(st)
    srv._source_total(st)
    assert loads


def test_has_findings_on_large_project_does_not_run_validation(
    tmp_path, make_config, monkeypatch,
) -> None:
    st = _state(tmp_path, make_config)
    monkeypatch.setattr(srv, "FULL_FINDINGS_THRESHOLD", 1)
    ran = []
    monkeypatch.setattr(
        srv, "run_validation", lambda *a, **k: ran.append(1) or (_ for _ in ()).throw(AssertionError),
    )
    out = srv.messages(st, ["pl"], "__all__", "", "has_findings")
    assert ran == []
    assert out["counts"]["total"] == 0


def test_message_index_cache_is_lru_and_small(tmp_path, make_config) -> None:
    st = _state(tmp_path, make_config)
    assert srv._INDEX_CACHE_CAP == 8
    srv._message_index(st, ["pl"], "app")
    for i in range(12):
        srv._message_index(st, ["pl", f"x{i}"], "app")
        srv._message_index(st, ["pl"], "app")  # touch: stays recent
    assert isinstance(st._message_index_cache, OrderedDict)
    assert len(st._message_index_cache) <= srv._INDEX_CACHE_CAP
    assert (("pl",), "app") in st._message_index_cache


def test_findings_cache_is_lru(tmp_path, make_config) -> None:
    st = _state(tmp_path, make_config)
    srv.findings(st, "pl", "app")
    assert isinstance(st._findings_cache, OrderedDict)


def test_lazy_haystack_and_targets_hoisted(tmp_path, make_config, monkeypatch) -> None:
    st = _state(tmp_path, make_config)
    loads = []
    real = st.catalog.load
    monkeypatch.setattr(st.catalog, "load", lambda *a, **k: loads.append(a) or real(*a, **k))
    from llm_localizator.web.index import MessageIndex

    index = MessageIndex.build(st, ["pl"], "app")
    pl_loads = [a for a in loads if a[0] == "pl"]
    assert len(pl_loads) == 1
    row = index.rows[0]
    assert row._haystack is None
    assert "a" in row.haystack
    assert row._haystack is not None
