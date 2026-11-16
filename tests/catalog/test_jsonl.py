from __future__ import annotations

import json

from llm_localizator.catalog.jsonl import load_jsonl_objects, rewrite_jsonl_lines


def test_load_jsonl_counts_malformed(tmp_path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(
        '{"a":1}\nnot-json\n{"b":2}\n[]\n',
        encoding="utf-8",
    )
    rows, bad = load_jsonl_objects(path)
    assert [r for r in rows] == [{"a": 1}, {"b": 2}]
    assert bad == 2


def test_rewrite_jsonl_roundtrip(tmp_path) -> None:
    path = tmp_path / "y.jsonl"
    rewrite_jsonl_lines(path, [json.dumps({"k": 1}), json.dumps({"k": 2})])
    rows, bad = load_jsonl_objects(path)
    assert bad == 0
    assert rows == [{"k": 1}, {"k": 2}]
