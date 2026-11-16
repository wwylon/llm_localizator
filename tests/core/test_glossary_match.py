"""Source-aware glossary hits for prompts."""

from __future__ import annotations

from llm_localizator.core.glossary_match import (
    format_glossary_annotation,
    glossary_hits,
)
from llm_localizator.pipeline.prompts import BatchItem, build_batch_prompt, build_single_prompt
from llm_localizator.projects.context import glossary_prompt_block


def _gloss() -> dict:
    return {
        "doNotTranslate": ["Stayman", "Blackwood"],
        "terms": {
            "staff": {
                "ar": "الموظفون",
                "note": "admin sidebar — roles and grants",
            },
            "trick": {
                "pl": "lewa",
                "pl_forbidden": ["sztuczka"],
            },
            "bid": {
                "pl": "zapowiedź",
                "ar": "المزايدة",
            },
            "table": {"pl": "stół"},
        },
    }


def test_staff_hits_staff_not_table() -> None:
    hits = glossary_hits("Staff", _gloss(), "ar")
    terms = {h.term for h in hits if h.kind == "term"}
    assert "staff" in terms
    assert "table" not in terms


def test_plural_tricks_hits_trick() -> None:
    hits = glossary_hits("Two tricks", _gloss(), "pl")
    assert any(h.term == "trick" for h in hits)


def test_bidding_does_not_hit_bid() -> None:
    hits = glossary_hits("Bidding is open", _gloss(), "pl")
    assert not any(h.term == "bid" for h in hits)


def test_dnt_hit() -> None:
    hits = glossary_hits("Use Stayman here", _gloss(), "pl")
    assert any(h.kind == "dnt" and h.term == "Stayman" for h in hits)


def test_annotation_format() -> None:
    hits = glossary_hits("Staff", _gloss(), "ar")
    note = format_glossary_annotation(hits)
    assert note.startswith("[glossary:")
    assert "staff" in note
    assert "الموظفون" in note


def test_glossary_hits_prefer_locale_note() -> None:
    gloss = {
        "doNotTranslate": [],
        "terms": {
            "bid": {
                "pl": "zapowiedź",
                "ar": "المزايدة",
                "note": "shared legacy",
                "ar_note": "Arabic auction call",
                "pl_note": "Polish auction call",
            },
        },
    }
    ar = glossary_hits("Make a bid", gloss, "ar")
    assert ar[0].note == "Arabic auction call"
    pl = glossary_hits("Make a bid", gloss, "pl")
    assert pl[0].note == "Polish auction call"
    de = glossary_hits("Make a bid", gloss, "de")
    assert de[0].note == "shared legacy"


def test_batch_prompt_per_item_glossary() -> None:
    gloss = _gloss()
    items = [
        BatchItem(
            source="Staff",
            message_key="admin.navStaff",
            glossary_note=format_glossary_annotation(
                glossary_hits("Staff", gloss, "ar"),
            ),
        ),
        BatchItem(source="Hello", message_key="admin.hello"),
    ]
    preamble = glossary_prompt_block(gloss, "ar", "Arabic", sources=[i.source for i in items])
    assert "الموظفون" not in preamble  # terms not in preamble
    assert "Stayman" not in preamble  # DNT not in these sources

    prompt = build_batch_prompt(
        items, "Arabic", "ar", "demo", preamble,
    )
    assert "[glossary:" in prompt
    assert "staff" in prompt
    # Second item has no glossary annotation
    assert prompt.count("[glossary:") == 1


def test_slim_preamble_dnt_filtered() -> None:
    gloss = _gloss()
    block = glossary_prompt_block(
        gloss, "pl", "Polish", sources=["Use Stayman"],
    )
    assert "Stayman" in block
    assert "Blackwood" not in block
    assert "lewa" not in block  # no term dump


def test_single_prompt_includes_glossary_note() -> None:
    item = BatchItem(
        source="Staff",
        glossary_note="[glossary: 'staff'→'الموظفون']",
    )
    prompt = build_single_prompt(item, "Arabic", "demo", "")
    assert "[glossary: 'staff'→'الموظفون']" in prompt
