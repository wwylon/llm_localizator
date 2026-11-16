"""Skeleton ICU strategy: the sentence once, each span alone (ADR-132)."""

from __future__ import annotations

from types import SimpleNamespace

from llm_localizator.pipeline import translate_icu as ti

SOURCE = "Last hand: {who, select, you {You} other {{who}}} took {n, plural, one {# trick} other {# tricks}}."
SPANS = {
    "{who, select, you {You} other {{who}}}": "{who, select, you {Ty} other {{who}}}",
    "{n, plural, one {# trick} other {# tricks}}":
        "{n, plural, one {# lewę} few {# lewy} many {# lew} other {# lewy}}",
}


def _run(monkeypatch, sentence):
    monkeypatch.setattr(ti, "_complete_span", lambda *a, **k: sentence)
    monkeypatch.setattr(ti, "_translate_icu_span", lambda p, seg, *a, **k: SPANS.get(seg))
    cfg = SimpleNamespace(domain="", style_for=lambda *a: (None, ""), catalog_standard=None)
    payload = SimpleNamespace(source=SOURCE, placeholder_mask=None, html=False)
    notes: list[str] = []
    out = ti._translate_icu_skeleton(None, payload, "Polish", "pl", "m", cfg, "", "informal",
                                     notes.append, glossary={})
    return out, notes


def test_skeleton_reassembles_spans_into_the_translated_sentence(monkeypatch) -> None:
    out, notes = _run(monkeypatch, "Ostatnie rozdanie: {__icu0} wziął {__icu1}.")
    assert out == ("Ostatnie rozdanie: {who, select, you {Ty} other {{who}}} wziął "
                   "{n, plural, one {# lewę} few {# lewy} many {# lew} other {# lewy}}."), notes


def test_skeleton_rejects_a_lost_token(monkeypatch) -> None:
    out, notes = _run(monkeypatch, "Ostatnie rozdanie: {__icu0} wziął lewy.")
    assert out is None
    assert any("token" in n for n in notes)


def test_select_branches_keep_edge_punctuation_and_empty_branches(monkeypatch) -> None:
    words = {"alone": "samotnie", "coinched": "z kontrą", "surcoinched": "z rekontrą"}
    monkeypatch.setattr(ti, "_complete_span", lambda p, prompt, src, *a: words[src])
    cfg = SimpleNamespace(domain="", style_for=lambda *a: (None, ""))
    run = lambda seg: ti._translate_select_branches(None, seg, "Polish", "pl", "m", cfg, "", "", {})
    assert run("{lone, select, yes {, alone} other {}}") == "{lone, select, yes {, samotnie} other {}}"
    assert run("{mult, select, 2 { coinched} 4 { surcoinched} other {}}") == (
        "{mult, select, 2 { z kontrą} 4 { z rekontrą} other {}}")
    assert ti._select_branches("{n, plural, one {x} other {y}}") is None
