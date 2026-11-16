"""Ambiguity notes (C-033)."""

from __future__ import annotations

import json

from llm_localizator.pipeline.ambiguity import MAX_NOTES, ambiguity_notes, build_ambiguity_prompt, parse_ambiguity
from llm_localizator.providers import ProviderError


class _Provider:
    def __init__(self, reply=None, error=None) -> None:
        self.reply, self.error, self.requests = reply, error, []

    def complete(self, req):
        self.requests.append(req)
        if self.error:
            raise self.error
        return self.reply


def test_parse_keeps_valid_notes_and_caps_them() -> None:
    rows = [{"term": f"t{i}", "senses": ["a", "b"], "chosen": "a"} for i in range(5)]
    notes = parse_ambiguity(json.dumps({"notes": rows}))
    assert len(notes) == MAX_NOTES and notes[0] == {"term": "t0", "senses": ["a", "b"], "chosen": "a"}


def test_parse_drops_incomplete_rows_and_survives_junk() -> None:
    assert parse_ambiguity("not json") == []
    assert parse_ambiguity(json.dumps({"notes": [{"term": "x"}, "bad", {"term": "y", "chosen": "z"}]})) == [
        {"term": "y", "senses": [], "chosen": "z"},
    ]
    assert parse_ambiguity('Sure! {"notes": []} done') == []


def test_notes_come_from_the_provider_and_failure_gives_none() -> None:
    good = _Provider(json.dumps({"notes": [{"term": "Book", "senses": ["reserve", "volume"], "chosen": "reserve"}]}))
    out = ambiguity_notes(good, "m", source="Book now", translated="Zarezerwuj", language="Polish")
    assert out[0]["term"] == "Book" and "Book now" in good.requests[0].prompt
    assert ambiguity_notes(_Provider(error=ProviderError("down")), "m", source="a", translated="b", language="Polish") == []


def test_prompt_carries_context_only_when_given() -> None:
    assert "Context:" not in build_ambiguity_prompt("a", "b", "Polish")
    assert "Context: footer" in build_ambiguity_prompt("a", "b", "Polish", "footer")
