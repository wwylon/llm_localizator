"""Project-maintained inflected forms: ``<locale>_forms`` beside the approved term."""

from __future__ import annotations

from llm_localizator.catalog.glossary_exchange import COLUMNS, export_csv, export_tbx, parse_csv
from llm_localizator.core.glossary_match import format_glossary_annotation, glossary_hits
from llm_localizator.core.validate import glossary_violations
from llm_localizator.projects.glossary_edit import _apply_record

BID = {"terms": {"bid": {"pl": "zapowiedź", "pl_forms": ["zapowiedzi", "zapowiedzią"]}}}


def _kinds(translated: str, glossary: dict = BID, locale: str = "pl") -> set[str]:
    return {i.kind for i in glossary_violations("Place a bid", translated, glossary, locale)}


def test_a_listed_form_satisfies_the_approved_term() -> None:
    assert "missing-approved" not in _kinds("Złóż zapowiedzi")


def test_forms_work_where_the_stem_heuristic_does_not_apply() -> None:
    # German does not use the stem fallback, so only the explicit list can accept this.
    glossary = {"terms": {"bid": {"de": "Gebot", "de_forms": ["Geboten"]}}}
    assert "missing-approved" not in _kinds("Ein Angebot mit Geboten", glossary, "de")
    assert "missing-approved" in _kinds("Ein Angebot", glossary, "de")


def test_an_unlisted_word_still_fires() -> None:
    assert "missing-approved" in _kinds("Złóż aukcją")


def test_the_annotation_lists_the_allowed_forms() -> None:
    hits = glossary_hits("Place a bid", BID, "pl")
    assert format_glossary_annotation(hits) == (
        "[glossary: use 'bid'→'zapowiedź' (also: zapowiedzi, zapowiedzią)]"
    )


def test_forms_key_is_never_exported_as_a_locale() -> None:
    csv_text = export_csv(BID)
    assert "pl_forms" not in csv_text
    assert csv_text.splitlines()[0] == ",".join(COLUMNS) + ",forms"
    assert "pl_forms" not in export_tbx(BID, source_locale="en")


def test_csv_without_forms_keeps_the_original_header() -> None:
    plain = {"terms": {"bid": {"pl": "zapowiedź"}}}
    assert export_csv(plain).splitlines()[0] == ",".join(COLUMNS)


def test_forms_survive_a_csv_round_trip() -> None:
    (record,) = parse_csv(export_csv(BID), path="g.csv")
    assert record.translations == {"pl": "zapowiedź"}
    assert record.forms == {"pl": ["zapowiedzi", "zapowiedzią"]}
    data: dict = {"terms": {}, "doNotTranslate": []}
    _apply_record(data, record)
    assert data["terms"]["bid"]["pl_forms"] == ["zapowiedzi", "zapowiedzią"]


def test_importing_a_legacy_csv_keeps_existing_forms() -> None:
    legacy = "term,locale,translation,forbidden,note\nbid,pl,zapowiedź,,\n"
    (record,) = parse_csv(legacy, path="old.csv")
    data = {"terms": {"bid": dict(BID["terms"]["bid"])}, "doNotTranslate": []}
    _apply_record(data, record)
    assert data["terms"]["bid"]["pl_forms"] == ["zapowiedzi", "zapowiedzią"]


def test_editing_a_term_in_the_web_editor_keeps_its_forms(tmp_path) -> None:
    import json

    from llm_localizator.projects.glossary_edit import mutate_glossary

    (tmp_path / "global.json").write_text(json.dumps({
        "doNotTranslate": [], "terms": {"bid": dict(BID["terms"]["bid"])},
    }), encoding="utf-8")
    mutate_glossary(
        tmp_path, domain="global", action="edit", term="bid", translations={"pl": "oferta"},
    )
    saved = json.loads((tmp_path / "global.json").read_text(encoding="utf-8"))["terms"]["bid"]
    assert saved["pl"] == "oferta"
    assert saved["pl_forms"] == ["zapowiedzi", "zapowiedzią"]
