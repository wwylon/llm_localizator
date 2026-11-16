"""Write floor and never-worse (plan Part C, C2 / E8)."""

from __future__ import annotations

from types import SimpleNamespace

from llm_localizator.catalog.scores import text_sha
from llm_localizator.core.hash import src_hash
from llm_localizator.pipeline.write_policy import hold_reason, write_floor

SRC = "Zoom images ({n})"
CUR = "Powiększ obrazy ({n})"


def _q(score, scorer="bt", dims=None):
    return SimpleNamespace(score=score, scorer=scorer, dimensions=dims)


def _cfg(floor=None):
    return SimpleNamespace(write_floor=floor)


def _hold(quality, *, previous=CUR, src=SRC, entry_src=SRC, old=0.9, old_scorer="bt", text="Zbliż obrazki ({n})"):
    return hold_reason(
        _cfg(), source=src, previous=previous,
        entry={"src_sha": src_hash(entry_src)},
        old_score={"quality_score": old, "scorer": old_scorer, "text_sha": text_sha(previous or "")},
        text=text, quality=quality,
    )


def test_weaker_rerun_keeps_the_current_text() -> None:
    reason = _hold(_q(0.7))
    assert reason and "not better" in reason


def test_better_rerun_is_written() -> None:
    assert _hold(_q(0.97)) is None


def test_changed_source_always_writes() -> None:
    assert _hold(_q(0.7), entry_src="Zoom image") is None


def test_scores_on_different_scales_are_not_compared() -> None:
    assert _hold(_q(0.7), old_scorer="lqs") is None


def test_first_translation_has_nothing_to_beat() -> None:
    assert _hold(_q(0.7), previous=None) is None
    assert _hold(_q(0.7), previous=SRC) is None  # English fallback is not a translation


def test_below_floor_is_held_even_without_a_current_text() -> None:
    reason = _hold(_q(0.2), previous=None)
    assert reason and "write floor" in reason
    assert _hold(_q(0.4, scorer="lqs"), previous=None)
    assert _hold(_q(0.1, scorer="heuristic"), previous=None) is None


def test_floor_defaults_and_override() -> None:
    assert write_floor(_cfg(), "lqs") == 0.5
    assert write_floor(_cfg(), "bt") == 0.35
    assert write_floor(_cfg(0.6), "bt") == 0.6
