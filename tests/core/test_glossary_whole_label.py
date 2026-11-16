"""A label that IS a glossary term must use the approved word (ADR-127)."""

from __future__ import annotations

from llm_localizator.core.validate import glossary_violations, validate_translation

G = {"terms": {"ten": {"pl": "dziesiątka"}, "hearts": {"pl": "kier"}, "deal": {"pl": "rozdanie"}}}


def _blocking(src, out):
    return [i.kind for i in glossary_violations(src, out, G, "pl") if i.blocking]


def test_whole_label_term_must_use_the_approved_word() -> None:
    assert _blocking("Ten", "Dziesiętka") == ["missing-approved"]
    assert _blocking("Hearts", "Hearts") == ["missing-approved"]
    assert _blocking("Ten:", "Dziesiątka:") == []
    assert not validate_translation("Ten", "Dziesiętka", "pl", G)[0]


def test_inflected_and_longer_sources_stay_advisory() -> None:
    assert _blocking("Deal", "Rozdaj") == []  # stem match: verb form of the approved noun
    assert _blocking("Ten of hearts wins", "Dziesiątka kier wygrywa") == []
    assert _blocking("Play the ten now", "Zagraj teraz dziesiątkę") == []
