"""The bridge import failure: an agent CSV escaped commas as ``\\,`` and left others unquoted, and
the importer silently kept only the text before the first comma."""

from __future__ import annotations

import json

from llm_localizator.catalog import build_catalog
from llm_localizator.ops.dispatch import dispatch_op

from .factory import build_project
from .specs import DEFECTS, GOLD


def _import(cfg, text: str) -> dict:
    out = dispatch_op(cfg, "import", {"text": text, "format": "csv", "locales": ["pl"]}, actor_role="Admin")
    return out.get("data") or out


def _broken_project(tmp_path):
    """pl resetHint holds the truncated bridge value, so a repaired import has something to fix."""
    return build_project(tmp_path, defects=[d for d in DEFECTS if d.id == "backslash-cut-pl"])


def test_escaped_and_unquoted_commas_are_rejoined(tmp_path) -> None:
    cfg = _broken_project(tmp_path).config()
    want = GOLD["pl"]["app"]["resetHint"]
    bad_value = want.replace(", ", "\\, ")  # backslash before the comma, as the agent wrote it
    data = _import(cfg, "namespace,key,en,pl\n" + "app,resetHint,x," + bad_value + "\n")
    assert int(data.get("rejected") or 0) == 0, data.get("errors")
    assert int(data.get("accepted") or 0) == 1
    assert data["files"][0].get("repaired") is True
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    assert catalog.load("pl", "app")["resetHint"] == want


def test_quoted_backslash_comma_is_unescaped(tmp_path) -> None:
    cfg = _broken_project(tmp_path).config()
    want = GOLD["pl"]["app"]["resetHint"]
    quoted = '"' + want.replace(", ", "\\, ") + '"'
    data = _import(cfg, "namespace,key,en,pl\n" + "app,resetHint,x," + quoted + "\n")
    assert int(data.get("accepted") or 0) == 1
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    assert catalog.load("pl", "app")["resetHint"] == want


def test_a_wide_row_that_cannot_be_rejoined_is_rejected_not_truncated(tmp_path) -> None:
    cfg = build_project(tmp_path).config()
    data = _import(cfg, "namespace,key,en,pl\napp,save,Save,Zapisz,extra,cells\n")
    assert int(data.get("rejected") or 0) == 1
    assert "quote every field" in json.dumps(data.get("errors"))
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    assert catalog.load("pl", "app")["save"] == GOLD["pl"]["app"]["save"]
