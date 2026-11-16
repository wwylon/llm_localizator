"""C-007: approved-only export and bundle."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog.import_formats import load_catalog
from llm_localizator.catalog.state import StateStore
from llm_localizator.catalog.export_formats import render_export
from llm_localizator.projects.config import ConfigError, load_config
from llm_localizator.web.bundle import bundle_payload


def _project(tmp_path, extra=""):
    nl = chr(10)
    toml = nl.join([
        "[project]", 'name = "demo"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "messages/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "", extra, "",
    ])
    (tmp_path / ".llm-localize.toml").write_text(toml, encoding="utf-8")
    for loc, data in (("en", {"a": "One", "b": "Two"}), ("de", {"a": "Eins", "b": "Zwei"})):
        d = tmp_path / "messages" / loc
        d.mkdir(parents=True)
        (d / "app.json").write_text(json.dumps(data), encoding="utf-8")
    cfg = load_config(tmp_path / ".llm-localize.toml")
    store = StateStore(cfg.state_root())
    store.record("de", "app", "a", {"verified_at": "2026-01-01T00:00:00Z"})
    store.record("de", "app", "b", {})
    store.save("de")
    return cfg


def test_config_validates_level(tmp_path):
    with pytest.raises(ConfigError):
        _project(tmp_path, '[delivery]\nrequire = "bogus"'.replace("\n", chr(10)))


def test_export_blanks_unapproved(tmp_path):
    cfg = _project(tmp_path)
    cat = load_catalog(cfg)
    body, *_ = render_export(cfg, cat, locales=["de"], approved_only=True)
    text = body.decode("utf-8")
    assert "Eins" in text and "Zwei" not in text
    body, *_ = render_export(cfg, cat, locales=["de"])
    assert "Zwei" in body.decode("utf-8")


def test_bundle_falls_back_and_etag_changes(tmp_path):
    plain = bundle_payload(_project(tmp_path / "p"), locale="de") if (tmp_path / "p").mkdir() is None else None
    strict = bundle_payload(
        _project(tmp_path / "s", '[delivery]\nrequire = "verified"'.replace("\n", chr(10))),
        locale="de",
    ) if (tmp_path / "s").mkdir() is None else None
    assert plain["messages"]["app"]["b"] == "Zwei"
    assert strict["messages"]["app"] == {"a": "Eins", "b": "Two"}
    assert plain["etag"] != strict["etag"]
