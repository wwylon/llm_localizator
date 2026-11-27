"""Agent guide --print-steps (ADR-159)."""

from __future__ import annotations

from llm_localizator.help import agent_steps, format_agent_steps, guide_text


def test_agent_steps_from_section_headings() -> None:
    steps = agent_steps()
    assert len(steps) >= 5
    titles = " ".join(t for _, t in steps).lower()
    assert "hard rules" in titles
    assert "wiring" in titles or "hardcoded" in titles
    joined = format_agent_steps(steps)
    assert joined.startswith("1. ")
    assert "Ask before changing" in guide_text("agent")
    assert "check-keys" in guide_text("agent")
    assert "bakeoff" in guide_text("agent").lower()
