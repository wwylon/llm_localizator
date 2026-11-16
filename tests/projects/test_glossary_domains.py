"""Glossary domain subsets (R-10)."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.core.validate import glossary_violations
from llm_localizator.projects.context import (
    effective_glossary_for,
    load_glossary,
    load_glossary_bundle,
    select_glossary,
)
from llm_localizator.projects.config import CONFIG_FILENAME, load_config


MINIMAL = """
[project]
name = "demo"

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]
"""


def write_config(root: Path, body: str = MINIMAL) -> Path:
    path = root / CONFIG_FILENAME
    path.write_text(body, encoding="utf-8")
    return path


def test_single_file_glossary_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "glossary.json"
    path.write_text(
        json.dumps({
            "doNotTranslate": ["Ollama"],
            "terms": {"account": {"pl": "konto"}},
        }),
        encoding="utf-8",
    )
    g = load_glossary(path)
    assert g["doNotTranslate"] == ["Ollama"]
    assert g["terms"]["account"]["pl"] == "konto"


def test_directory_glossary_selects_domains(tmp_path: Path) -> None:
    gdir = tmp_path / "glossary"
    gdir.mkdir()
    (gdir / "global.json").write_text(
        json.dumps({"doNotTranslate": ["API"], "terms": {"save": {"pl": "zapisz"}}}),
        encoding="utf-8",
    )
    (gdir / "billing.json").write_text(
        json.dumps({"terms": {"invoice": {"pl": "faktura"}}}),
        encoding="utf-8",
    )
    (gdir / "games.json").write_text(
        json.dumps({"terms": {"pot": {"pl": "pula"}}}),
        encoding="utf-8",
    )
    bundle = load_glossary_bundle(gdir)
    billing = select_glossary(bundle, domains=["billing"])
    assert "invoice" in billing["terms"]
    assert "pot" not in billing["terms"]
    assert "save" in billing["terms"]  # global always merged
    assert "API" in billing["doNotTranslate"]

    games_only = effective_glossary_for(gdir, domains=["games"])
    assert "pot" in games_only["terms"]
    assert "invoice" not in games_only["terms"]


def test_validate_uses_domain_subset_only(tmp_path: Path) -> None:
    gdir = tmp_path / "glossary"
    gdir.mkdir()
    (gdir / "global.json").write_text(json.dumps({"terms": {}}), encoding="utf-8")
    (gdir / "billing.json").write_text(
        json.dumps({
            "terms": {
                "invoice": {"pl": "faktura", "pl_forbidden": ["rachunek"]},
            },
        }),
        encoding="utf-8",
    )
    # Using games-only subset: billing term must not fire.
    games = effective_glossary_for(gdir, domains=["games"])
    issues = glossary_violations("Pay the invoice", "Zapłać rachunek", games, "pl")
    assert issues == []

    billing = effective_glossary_for(gdir, domains=["billing"])
    issues = glossary_violations("Pay the invoice", "Zapłać rachunek", billing, "pl")
    assert any("forbidden" in i.message.lower() or "rachunek" in i.message for i in issues)


def test_config_glossary_domains_map(tmp_path: Path) -> None:
    body = MINIMAL + """
[prompt]
glossary = "glossary"
glossary_domains = { play = "games", account = ["account", "billing"] }
"""
    (tmp_path / "glossary").mkdir()
    cfg = load_config(write_config(tmp_path, body))
    assert cfg.glossary_domains["play"] == ["games"]
    assert cfg.glossary_domains["account"] == ["account", "billing"]
    assert cfg.glossary_domains_for("play") == ["games"]
    assert cfg.glossary_domains_for("play", key_domain="poker") == ["poker", "games"]
