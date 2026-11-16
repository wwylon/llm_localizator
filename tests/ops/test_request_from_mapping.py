"""request_from_mapping builds the same request from a web body and from CLI args (M3)."""

from __future__ import annotations

from types import SimpleNamespace

from llm_localizator.ops.types import ScanDecideRequest, request_from_mapping


def test_web_body_strings_are_coerced() -> None:
    req = request_from_mapping(ScanDecideRequest, {
        "action": "accept", "ids": "a1, b2", "limit": "5", "all_pending": "true", "confidence": "",
        "note": "ok", "unknown_field": "ignored",
    })
    assert req.action == "accept" and req.ids == ["a1", "b2"] and req.limit == 5
    assert req.all_pending is True and req.confidence is None and req.note == "ok"


def test_empty_and_missing_values_fall_back_to_defaults() -> None:
    req = request_from_mapping(ScanDecideRequest, {"action": "", "limit": "", "ids": ""})
    assert req.action == "status" and req.limit is None and req.ids is None and req.kind == "hit"


def test_cli_namespace_and_overrides() -> None:
    args = SimpleNamespace(action="ignore", kind="hit", ids=["x"], confidence="low", file=None,
                           all_pending=False, key=None, note="", by="cli", adapter=None, limit=None,
                           project="p", config=None, fmt="text")
    req = request_from_mapping(ScanDecideRequest, vars(args), by="tests")
    assert req.action == "ignore" and req.ids == ["x"] and req.confidence == "low" and req.by == "tests"
