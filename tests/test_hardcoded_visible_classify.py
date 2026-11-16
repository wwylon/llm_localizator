"""Hermetic tests for en-XX leftover classification (no Playwright)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EXP = Path(__file__).resolve().parents[1] / "experiments" / "hardcoded_visible"
if not _EXP.is_dir():
    pytest.skip("needs experiments/hardcoded_visible (dev checkout only)", allow_module_level=True)
sys.path.insert(0, str(_EXP))
from classify import is_leftover, is_pseudo_marker, normalize_for_match  # noqa: E402


def test_classify_pseudo_vs_leftover() -> None:
    assert is_pseudo_marker("XXXXXX")
    assert is_pseudo_marker("XXXX XXX XX XXXX…")
    assert is_pseudo_marker("  ")
    assert not is_pseudo_marker("System settings")
    assert is_leftover("System settings")
    assert not is_leftover("XXXXXX")
    assert not is_leftover("42%")
    assert normalize_for_match("  Hello   World ") == "hello world"


def test_identifiers_are_not_leftovers() -> None:
    for token in ("4b85e82ebde17155", "20261003T082745Z_euchre_full_00000001", "_test_play_fullinfo",
                  "_cli_demo", "RealESRGAN_x4plus"):
        assert not is_leftover(token), token
    # Real words, short codes and prose stay leftovers.
    for text in ("Settings", "Go alone", "heuristic", "Loading photo.jpg now", "t_rel"):
        assert is_leftover(text), text
