"""<string-array> resources map to flat ``name[i]`` keys and back."""

from __future__ import annotations

from llm_localizator.catalog import build_catalog

from .test_adapter_contract import FORMATS


def test_string_array_round_trip(tmp_path) -> None:
    cat = build_catalog("android-xml", tmp_path, FORMATS["android-xml"], "en")
    data = {"title": "Hi", "colors[0]": "Red", "colors[1]": "It's blue", "colors[2]": "Green"}
    cat.save("en", "app", dict(data))
    text = cat.path_for("en", "app").read_text(encoding="utf-8")
    assert '<string-array name="colors">' in text and text.count("<item>") == 3
    assert cat.load("en", "app") == data


def test_array_gap_keeps_positions(tmp_path) -> None:
    cat = build_catalog("android-xml", tmp_path, FORMATS["android-xml"], "en")
    cat.save("en", "app", {"a[0]": "x", "a[2]": "z"})
    assert cat.load("en", "app") == {"a[0]": "x", "a[1]": "", "a[2]": "z"}
