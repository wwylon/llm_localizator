"""C-031: throughput by source class."""

from __future__ import annotations

from llm_localizator.catalog.provenance import PROVIDERS, SOURCE_CLASSES, source_class
from llm_localizator.ops.console import _source_series


def test_every_provider_is_classified():
    for provider in PROVIDERS:
        assert source_class(provider) in SOURCE_CLASSES, provider


def test_classes():
    assert source_class("human") == "human"
    assert source_class("import") == "imported"
    assert source_class("deepl") == "mt" and source_class("ctranslate2") == "mt"
    assert source_class("anthropic") == "ai" and source_class("agent") == "ai"
    assert source_class("ollama", "tm-hit") == "tm"
    assert source_class("human", "tm-hit") == "human"


def test_series_counts_only_dated_window_keys():
    days = ["2026-10-01", "2026-10-02"]
    out = _source_series(
        [("ai", "2026-10-01"), ("ai", "2026-10-02"), ("human", "2026-10-02"),
         ("tm", ""), ("mt", "2026-09-01")], days)
    assert out["ai"] == [1, 1] and out["human"] == [0, 1]
    assert out["tm"] == [0, 0] and out["mt"] == [0, 0]
    assert set(out) == set(SOURCE_CLASSES)


def test_progress_payload_has_sources(project_root, make_config):
    from llm_localizator.ops.console import progress_payload
    from tests.conftest import setup_project

    setup_project(project_root, {"a": "Hi"}, existing={"a": "Czesc"})
    series = progress_payload(make_config(project_root))["series"]
    assert set(series["sources"]) == set(SOURCE_CLASSES)
    assert all(len(v) == len(series["days"]) for v in series["sources"].values())
