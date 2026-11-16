"""Suggest alternatives from other roles (C-011)."""

from __future__ import annotations

from types import SimpleNamespace

from llm_localizator.ops import suggest as sg
from llm_localizator.providers import ProviderError


def _cfg(secondary=None, primary="m1", default="m3"):
    return SimpleNamespace(
        role_for=lambda _l: SimpleNamespace(secondary=secondary, primary=primary),
        models={"default": default},
    )


def _score(_t):
    return SimpleNamespace(score=0.8, signals=[])


def test_alternatives_skip_used_and_duplicate_text() -> None:
    texts = {"m2": "Cześć", "m3": "Witaj"}
    out: list[str] = []
    alts = sg._alternatives(_cfg("m2"), "pl", "m1", "Cześć", None, lambda m: texts[m], _score, out)
    assert [(a["model"], a["text"]) for a in alts] == [("m3", "Witaj")]  # m2 repeats the text, m1 already used
    assert out == ["alternative (m3): Witaj"]


def test_alternatives_survive_a_failing_model_and_cap_at_two() -> None:
    def run(m):
        if m == "m2":
            raise ProviderError("down")
        return f"text-{m}"

    cfg = _cfg("m2", primary="m4", default="m3")
    alts = sg._alternatives(cfg, "pl", "m1", "base", None, run, _score, [])
    assert [a["model"] for a in alts] == ["m4", "m3"]


def test_cloud_projects_get_no_alternatives() -> None:
    assert sg._alternatives(_cfg("m2"), "pl", "m1", "x", "openai", lambda m: "y", _score, []) == []
