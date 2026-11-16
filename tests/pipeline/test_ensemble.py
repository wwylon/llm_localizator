"""Selective dual-candidate policy (ADR-21)."""

from __future__ import annotations

from llm_localizator.core.quality import QualityResult
from llm_localizator.pipeline.ensemble import (
    CandidateRecord,
    needs_secondary_pass,
    pick_better,
)
from llm_localizator.projects.config import LocaleRole


def test_needs_secondary_when_prefer_secondary(make_config, project_root) -> None:
    cfg = make_config(
        project_root,
        roles={"pl": LocaleRole(secondary="alt", prefer_secondary=True)},
    )
    q = QualityResult(score=0.99, signals=[], scorer="bt")
    assert needs_secondary_pass(
        cfg, "pl", source="Hello", translated="Witaj", quality=q,
    )


def test_needs_secondary_for_icu_placeholders(make_config, project_root) -> None:
    cfg = make_config(
        project_root,
        roles={"pl": LocaleRole(primary="a", secondary="b")},
        quality_threshold=0.1,
    )
    q = QualityResult(score=0.99, signals=[], scorer="bt")
    assert needs_secondary_pass(
        cfg, "pl",
        source="Hello {name}", translated="Witaj {name}", quality=q,
    )


def test_no_secondary_without_role(make_config, project_root) -> None:
    cfg = make_config(project_root)
    q = QualityResult(score=0.1, signals=["low"], scorer="bt")
    assert not needs_secondary_pass(
        cfg, "pl", source="delete account", translated="x", quality=q,
    )


def test_pick_better_prefers_higher_score() -> None:
    primary = CandidateRecord("a", "m1", 0.4, "ollama", [])
    secondary = CandidateRecord("b", "m2", 0.8, "ollama", [])
    winner, payload = pick_better(primary, secondary)
    assert winner.text == "b"
    assert winner.model == "m2"
    assert len(payload) == 2


def test_pick_better_keeps_primary_on_tie() -> None:
    primary = CandidateRecord("a", "m1", 0.5, "ollama", [])
    secondary = CandidateRecord("b", "m2", 0.5, "ollama", [])
    winner, _ = pick_better(primary, secondary)
    assert winner.model == "m1"


def test_expansion_band_alone_never_triggers_a_paid_second_call(make_config, project_root) -> None:
    cfg = make_config(
        project_root,
        roles={"pl": LocaleRole(primary="a", secondary="b")},
    )
    q = QualityResult(score=0.99, signals=[], scorer="bt")
    # A translation many times longer than the source trips V14 but scores well.
    assert not needs_secondary_pass(
        cfg, "pl", source="Save changes now", translated="Zapisz " * 40, quality=q,
    )
