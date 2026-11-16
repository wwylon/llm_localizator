"""Inline do-not-translate markers (C-034)."""

from __future__ import annotations

from llm_localizator.core.dnt_spans import check_dnt_spans, dnt_spans, has_dnt_markers
from llm_localizator.core.validate import validate_translation_detailed
from llm_localizator.pipeline.placeholder_mask import mask_bare_placeholders, restore_placeholders

SRC = 'Open <span translate="no">Acme Cloud</span> and click <b>Save</b>.'


def test_finds_marked_elements_only() -> None:
    spans = dnt_spans(SRC)
    assert [t for _s, _e, t in spans] == ['<span translate="no">Acme Cloud</span>']
    assert has_dnt_markers(SRC) and not has_dnt_markers("Open <b>Acme</b>")


def test_notranslate_class_nested_and_void() -> None:
    nested = '<div class="a notranslate">x <div>y</div> z</div> tail'
    assert dnt_spans(nested)[0][2] == '<div class="a notranslate">x <div>y</div> z</div>'
    assert dnt_spans('See <img translate="no" src="a.png" /> now')[0][2] == '<img translate="no" src="a.png" />'
    assert dnt_spans('<span translate="no">never closed') == []


def test_check_requires_verbatim_element() -> None:
    ok = 'Otwórz <span translate="no">Acme Cloud</span> i kliknij <b>Zapisz</b>.'
    assert check_dnt_spans(SRC, ok) is None
    changed = 'Otwórz <span translate="no">Acme Chmura</span> i kliknij <b>Zapisz</b>.'
    assert "changed or missing" in check_dnt_spans(SRC, changed)
    assert check_dnt_spans("plain", "zwykły") is None


def test_mask_round_trips_marked_element_with_placeholder_inside() -> None:
    text = 'Hi {name}, run <code translate="no">cmd {x}</code> now'
    masked, mapping = mask_bare_placeholders(text)
    assert "translate" not in masked and "cmd" not in masked
    assert len(mapping) == 2  # {name} and the whole <code> element
    assert restore_placeholders(masked, mapping) == text


def test_detailed_validation_warns_with_v42() -> None:
    ok, warns = validate_translation_detailed(
        SRC, 'Otwórz <span translate="no">Acme</span> i kliknij <b>Zapisz</b>.', "pl", {},
    )
    assert any(w.id == "V42" for w in warns)
