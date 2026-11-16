"""``llm-localizator set``: one translation through the gate, with stamps (ADR-122)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.ops.set_translation import op_set

SOURCE = {
    "app.discard": "Discard {card}",
    "app.title": "Settings",
    "app.count": "{n, plural, one {# file} other {# files}}",
}


@pytest.fixture
def consumer(tmp_path: Path, make_config):
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps(SOURCE), encoding="utf-8")
    (tmp_path / "locales" / "pl.json").write_text(json.dumps({"app.discard": "Zrzutka {card}"}),
                                                  encoding="utf-8")
    cfg = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json",
                      targets=["pl"], state_dir=tmp_path / ".state")
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    return cfg, catalog


def test_set_writes_and_stamps_agent(consumer) -> None:
    cfg, catalog = consumer
    result = op_set(cfg, locale="pl", key="app.discard", text="Odrzuć {card}", model="claude-opus-5-5")
    assert result.ok, result.summary
    assert catalog.load("pl", None)["app.discard"] == "Odrzuć {card}"
    assert result.data["previous"] == "Zrzutka {card}" and result.data["by"] == "agent"
    history = (cfg.root / ".state").rglob("*")
    assert any(p.is_file() for p in history)


def test_set_normalizes_and_refuses_gate_failures(consumer) -> None:
    cfg, catalog = consumer
    quoted = op_set(cfg, locale="pl", key="app.title", text='"Ustawienia"')
    assert quoted.ok and catalog.load("pl", None)["app.title"] == "Ustawienia"
    assert any("quotes" in line for line in quoted.lines)
    broken = op_set(cfg, locale="pl", key="app.discard", text="Odrzuć kartę")  # placeholder lost
    assert broken.exit_code == 1 and "gate" in broken.summary
    assert catalog.load("pl", None)["app.discard"] == "Zrzutka {card}"
    forced = op_set(cfg, locale="pl", key="app.discard", text="Odrzuć kartę", force=True)
    assert forced.ok and forced.data["forced"] is True


def test_set_validates_its_arguments(consumer) -> None:
    cfg, _catalog = consumer
    assert op_set(cfg, locale="en", key="app.title", text="x").exit_code == 2
    assert op_set(cfg, locale="de", key="app.title", text="x").exit_code == 2
    assert op_set(cfg, locale="pl", key="app.nope", text="x").exit_code == 2
    assert op_set(cfg, locale="pl", key="app.title", text="x", by="robot").exit_code == 2


def test_unchanged_text_is_a_no_op(consumer) -> None:
    cfg, _catalog = consumer
    assert op_set(cfg, locale="pl", key="app.discard", text="Zrzutka {card}").data["changed"] is False
