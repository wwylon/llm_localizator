"""Saving a catalogue must not destroy content the adapter does not model."""

from __future__ import annotations

import json

from llm_localizator.catalog.json_nested import JsonNestedCatalog
from llm_localizator.catalog.php_array import _parse_php


def _catalog(tmp_path):
    return JsonNestedCatalog(tmp_path, "{locale}.json")


def test_json_nested_keeps_non_string_leaves_on_save(tmp_path) -> None:
    (tmp_path / "pl.json").write_text(json.dumps({
        "title": "Tytuł", "limit": 5, "flags": [1, 2], "on": True,
        "box": {"label": "Etykieta", "max": 10},
    }), encoding="utf-8")
    cat = _catalog(tmp_path)
    msgs = cat.load("pl")
    msgs["title"] = "Nowy"
    cat.save("pl", None, msgs)
    raw = json.loads((tmp_path / "pl.json").read_text(encoding="utf-8"))
    assert raw["title"] == "Nowy"
    assert raw["limit"] == 5 and raw["flags"] == [1, 2] and raw["on"] is True
    assert raw["box"] == {"label": "Etykieta", "max": 10}


def test_json_nested_deleting_a_string_key_still_works(tmp_path) -> None:
    (tmp_path / "pl.json").write_text(json.dumps({"a": "A", "n": 1}), encoding="utf-8")
    cat = _catalog(tmp_path)
    cat.save("pl", None, {})
    raw = json.loads((tmp_path / "pl.json").read_text(encoding="utf-8"))
    assert raw == {"n": 1}


def test_php_parse_roundtrip_of_common_shapes() -> None:
    text = "<?php\nreturn [\n    'a' => 'A',\n    \"b\" => \"B" + chr(92) + "n\",\n    'n' => [\n        'c' => 'C',\n    ],\n];\n"
    assert _parse_php(text) == {"a": "A", "b": "B\n", "n.c": "C"}
