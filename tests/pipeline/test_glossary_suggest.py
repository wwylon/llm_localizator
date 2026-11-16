"""``glossary-propose --locale`` mines the TM for terms the glossary lacks (ADR-52)."""

from __future__ import annotations

from llm_localizator.catalog.glossary_exchange import parse_csv
from llm_localizator.catalog.tm import TranslationMemory
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.source_ops import op_glossary_propose
from llm_localizator.pipeline.glossary_suggest import suggest_terms

from ..conftest import write_json

BIDS = [
    ("Place a bid now", "Złóż zapowiedź teraz"),
    ("Cancel your bid", "Anuluj swoją zapowiedź"),
    ("Bid history", "Historia zapowiedź"),
    ("Winning bid shown", "Zwycięska zapowiedź widoczna"),
    ("Raise the bid", "Podnieś zapowiedź"),
    ("Your bid was lower", "Twoja zapowiedź była niższa"),
]
NOISE = [("Save changes", "Zapisz zmiany"), ("Open the menu", "Otwórz menu")]


def test_a_repeated_pairing_is_suggested_and_noise_is_not() -> None:
    found = suggest_terms(BIDS + NOISE, min_occurrences=5)
    assert [(s.term, s.translation, s.count) for s in found] == [("bid", "zapowiedź", 6)]


def test_known_terms_and_thin_evidence_are_left_out() -> None:
    assert suggest_terms(BIDS, known={"Bid"}, min_occurrences=5) == []
    assert suggest_terms(BIDS[:3], min_occurrences=5) == []


def _tm(cfg, pairs):
    tm = TranslationMemory(cfg.tm_root())
    for source, text in pairs:
        tm.record(locale="pl", source=source, text=text, model="m")


def test_op_prints_an_importable_csv(project_root, make_config) -> None:
    cfg = make_config(project_root)
    _tm(cfg, BIDS + NOISE)
    result = op_glossary_propose(cfg, locale="pl", min_occurrences=5)
    assert result.ok and result.data["suggestions"] == 1
    records = parse_csv("\n".join(result.lines) + "\n", path="suggestions.csv")
    assert [(r.term, r.translations) for r in records] == [("bid", {"pl": "zapowiedź"})]


def test_op_writes_the_file_and_skips_glossary_terms(project_root, make_config) -> None:
    write_json(project_root / "glossary.json", {"terms": {"bid": {"pl": "oferta"}}})
    cfg = make_config(project_root, glossary_path=project_root / "glossary.json")
    _tm(cfg, BIDS)
    out = project_root / "out.csv"
    result = op_glossary_propose(cfg, locale="pl", out=str(out))
    assert result.data["suggestions"] == 0
    assert out.read_text(encoding="utf-8").startswith("term,locale,translation")


def test_unknown_locale_and_the_frequency_mode_still_work(project_root, make_config) -> None:
    cfg = make_config(project_root)
    assert not op_glossary_propose(cfg, locale="xx").ok
    assert dispatch_op(cfg, "glossary-propose", {}, actor_role="Admin")["ok"] is True
    assert dispatch_op(cfg, "glossary-propose", {"locale": "pl"}, actor_role="Admin")["ok"] is True
