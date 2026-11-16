"""Crawl dynamic text classified by origin (B1, ADR-133)."""

from __future__ import annotations

from llm_localizator.scan.dynamic_origin import classify_dynamic, json_strings, selector_pattern


def test_json_strings_keep_endpoint_and_field() -> None:
    got = json_strings({"tasks": [{"name": "train  model"}], "detail": "Task not found."}, "/api/tasks")
    assert got == {"train model": ("/api/tasks", "name"), "Task not found.": ("/api/tasks", "detail")}


def test_selector_pattern_drops_row_indices() -> None:
    assert selector_pattern("tr:nth-child(3) > td.name") == selector_pattern("tr:nth-child(9) > td.name")


def test_origins() -> None:
    responses = json_strings({"items": [{"title": "Deep nets"}], "error": "Queue is paused"}, "/api/x")
    rows = [{"page": "/", "text": "Deep nets", "selector": "li.t"},
            {"page": "/", "text": "Queue is paused", "selector": "div.alert"},
            {"page": "/", "text": "Built 3 minutes ago", "selector": "span.when"}]
    rows += [{"page": "/q", "text": f"job {i}", "selector": f"tr:nth-child({i}) > td"} for i in range(6)]
    out = {r["text"]: r for r in classify_dynamic(rows, responses)}
    assert out["Deep nets"]["origin"] == "api-data"
    assert out["Queue is paused"]["origin"] == "api-copy"
    assert out["Queue is paused"]["producer"] == "api:/api/x#error"
    assert out["Built 3 minutes ago"]["origin"] == "unknown"
    assert out["job 4"]["origin"] == "repeated"


def test_value_text() -> None:
    from llm_localizator.scan.dynamic_origin import is_value_text

    for text in ("GPU 5.4G", "71 MB", "2m53s", "48.1 / 62 GiB", "f3d5298", "CPU 0% RSS"):
        assert is_value_text(text), text
    for text in ("1 running", "Queue is paused", "64 GiB total · queue limit 97%", "All tasks"):
        assert not is_value_text(text), text
