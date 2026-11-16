"""Seeded round-trip fuzz: whatever an adapter saves, it must load back unchanged."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from llm_localizator.catalog import build_catalog

from .test_adapter_contract import FORMATS

FRAGMENTS = [
    "Hello", "Zażółć gęślą jaźń", "日本語", "مرحبا", "😀", "{name}", "%s", "%d items",
    '"quoted"', "it's", "back\\slash", "tab\there", "a\nb", "<b>bold</b>", "a & b",
    "100%", "{{.Count}}", "$HOME", "#hash", "key=value", "x: y", "- dash", "  lead", "trail  ",
    "semi;colon", "ünï", " nbsp",
]


def _messages(rng: random.Random, n: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(n):
        parts = rng.sample(FRAGMENTS, rng.randint(1, 3))
        out[f"key_{i}"] = " ".join(parts)
    return out


def _comparable(fmt: str, text: str) -> str:
    # Formats that cannot carry edge whitespace are compared stripped.
    return text.strip() if fmt in {"properties", "yaml", "csv", "ios-strings"} else text


@pytest.mark.parametrize("fmt", sorted(FORMATS))
@pytest.mark.parametrize("seed", range(5))
def test_random_messages_survive_a_save_load_cycle(fmt: str, seed: int, tmp_path: Path) -> None:
    rng = random.Random(f"{fmt}:{seed}")
    data = _messages(rng, rng.randint(1, 12))
    cat = build_catalog(fmt, tmp_path, FORMATS[fmt], "en")
    cat.save("en", "app", dict(data))
    loaded = cat.load("en", "app")
    assert {k: _comparable(fmt, v) for k, v in loaded.items()} == {
        k: _comparable(fmt, v) for k, v in data.items()
    }
    # A second cycle through the adapter must be stable.
    cat.save("en", "app", dict(loaded))
    assert cat.load("en", "app") == loaded
