"""Forbidden glossary variants match in any case and inflected form (plan Part C, C2 / E9)."""

from __future__ import annotations

from llm_localizator.core.validate import glossary_violations

GLOSSARY = {"terms": {"trick": {"pl": "lewa", "pl_forbidden": ["trik", "Tricki", "sztuczka"]},
                      "bid": {"pl": "zapowiedź", "pl_forbidden": ["oferta", "licytacja"]}}}


def _forbidden(src: str, out: str) -> list[str]:
    return [p.term for p in glossary_violations(src, out, GLOSSARY, "pl") if p.kind == "forbidden-variant"]


def test_inflected_and_capitalised_variants_fire() -> None:
    assert _forbidden("Tricks won", "Triki wzięte") == ["trick"]
    assert _forbidden("Take the trick", "Weź trikiem") == ["trick"]
    assert _forbidden("Tricks won", "Wygrane sztuczki") == ["trick"]
    assert _forbidden("Your bid", "Twoja oferty") == ["bid"]
    assert _forbidden("Your bid", "Twoja licytacją") == ["bid"]


def test_approved_term_and_unrelated_words_pass() -> None:
    assert _forbidden("Tricks won", "Wzięte lewy") == []
    assert _forbidden("Your bid", "Twoja zapowiedź") == []
    assert _forbidden("Your bid", "Trybik zapowiedzi") == []


def test_variant_only_counts_when_the_source_uses_the_term() -> None:
    assert _forbidden("Special offer", "Specjalna oferta") == []


def test_forbidden_plural_of_the_approved_term_matches_exactly() -> None:
    glossary = {"terms": {"clubs": {"pl": "trefl", "pl_forbidden": ["trefle", "kluby"]}}}
    issues = lambda out: [p.kind for p in glossary_violations("Clubs", out, glossary, "pl")
                          if p.kind == "forbidden-variant"]
    assert issues("Trefl") == []
    assert issues("Trefle") == ["forbidden-variant"]
    assert issues("Klubami") == ["forbidden-variant"]
