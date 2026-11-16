"""A label that is one glossary term gets the approved word, no model (ADR-128)."""

from __future__ import annotations

import json

from llm_localizator.catalog import build_catalog
from llm_localizator.core.validate import glossary_answer
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import NullProvider

G = {"terms": {"ten": {"pl": "dziesiątka"}, "hearts": {"pl": "kier"}, "bid": {"pl": "zapowiedź"},
               "upscale": {"pl_forbidden": ["ulepsz"]}}}


def test_glossary_answer() -> None:
    assert glossary_answer("Ten", G, "pl") == "Dziesiątka"
    assert glossary_answer("bid", G, "pl") == "zapowiedź"
    assert glossary_answer("Bid:", G, "pl") == "Zapowiedź:"
    assert glossary_answer("Ten of hearts", G, "pl") is None
    assert glossary_answer("Upscale", G, "pl") is None  # no approved word
    assert glossary_answer("Ten", G, "de") is None


def test_translate_uses_the_glossary_without_the_model(tmp_path, make_config) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps({"c.ten": "Ten", "c.hearts": "Hearts"}),
                                                  encoding="utf-8")
    (tmp_path / "glossary.json").write_text(json.dumps(G, ensure_ascii=False), encoding="utf-8")
    cfg = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json",
                      targets=["pl"], state_dir=tmp_path / ".state", glossary_path=tmp_path / "glossary.json")
    calls = []

    def handler(request):
        calls.append(request.prompt)
        return "WRONG"

    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    run_translation(cfg, catalog, NullProvider(handler=handler), batch_size=5, report=lambda *a, **k: None)
    pl = catalog.load("pl", None)
    assert pl == {"c.ten": "Dziesiątka", "c.hearts": "Kier"}
    assert not calls
