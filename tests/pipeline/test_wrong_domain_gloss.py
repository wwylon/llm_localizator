"""Soft cross-domain glossary signals (audit T5)."""

from __future__ import annotations

from llm_localizator.pipeline.judge import wrong_domain_glossary_signals


def test_foreign_forbidden_variant_is_signalled() -> None:
    own = {"terms": {"bid": {"pl": "licytacja"}}}
    foreign = {
        "terms": {
            "view": {
                "pl": "widok",
                "pl_forbidden": ["oferta"],  # poker "bid" bleed into UI "view"
            },
        },
    }
    # Source uses "view"; translation wrongly has the poker-forbidden form.
    signals = wrong_domain_glossary_signals(
        "Public view", "Publiczna oferta", "pl",
        own_glossary=own, foreign_glossary=foreign,
    )
    assert any(s.startswith("wrong_domain_gloss:forbidden-variant:") for s in signals)


def test_empty_foreign_glossary_is_silent() -> None:
    assert wrong_domain_glossary_signals(
        "Hello", "Cześć", "pl", own_glossary={}, foreign_glossary={},
    ) == []
