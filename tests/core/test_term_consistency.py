"""V48 cross-key term consistency (plan Part C, C2 / E9)."""

from __future__ import annotations

from llm_localizator.core.term_consistency import term_spreads

GLOSSARY = {"terms": {"bid": {"pl_variants": ["zapowiedź", "licytacja", "oferta"]},
                      "trick": {"pl": "lewa"}}}


def test_bid_drift_is_reported_with_the_majority() -> None:
    rows = [
        ("a", "Your bid", "Twoja zapowiedź"),
        ("b", "Last bid", "Ostatnia zapowiedź"),
        ("c", "Bid history", "Historia licytacji"),
        ("d", "Make a bid", "Złóż ofertę"),
        ("e", "Tricks", "Lewy"),
    ]
    [spread] = term_spreads(rows, GLOSSARY, "pl")
    assert spread.term == "bid" and spread.majority == "zapowiedź"
    assert spread.outliers == {"licytacja": ["c"], "oferta": ["d"]}


def test_consistent_terms_are_quiet() -> None:
    rows = [("a", "Your bid", "Twoja zapowiedź"), ("b", "Bids", "Zapowiedzi")]
    assert term_spreads(rows, GLOSSARY, "pl") == []
