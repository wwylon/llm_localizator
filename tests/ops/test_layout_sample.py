"""translate --sample layout[:N] (P5)."""

from __future__ import annotations

import json

import pytest

from llm_localizator.ops.layout_sample import layout_sample, parse_sample


def test_parse_sample() -> None:
    assert parse_sample(None) is None
    assert parse_sample("layout") == 60
    assert parse_sample("layout:12") == 12
    with pytest.raises(ValueError):
        parse_sample("random")


def test_sample_mixes_chrome_longest_and_spread(tmp_path, make_config) -> None:
    src = {f"nav.k{i}": "Save" for i in range(30)}
    src.update({f"help.p{i}": "A long paragraph " * (i + 1) for i in range(30)})
    src.update({f"table.t{i}": "Some table header text" for i in range(30)})
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps(src), encoding="utf-8")
    cfg = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json")
    keys = layout_sample(cfg, 12)
    assert len(keys) == 12 and len(set(keys)) == 12
    assert "help.p29" in keys  # the longest source
    assert any(k.startswith("nav.") for k in keys) and any(k.startswith("table.") for k in keys)
    assert layout_sample(cfg, 12) == keys  # deterministic
    assert len(layout_sample(cfg, 500)) == 90
