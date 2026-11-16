"""C-004: [exclude] key globs and source regexes."""

from __future__ import annotations

import pytest

from llm_localizator.projects.config import ConfigError, load_config


def _toml(extra: str) -> str:
    nl = chr(10)
    return nl.join([
        "[project]", 'name = "demo"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "messages/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "", extra, "",
    ])


def _cfg(tmp_path, extra):
    p = tmp_path / ".llm-localize.toml"
    p.write_text(_toml(extra), encoding="utf-8")
    return load_config(p)


def test_key_glob_and_namespace(tmp_path):
    cfg = _cfg(tmp_path, '[exclude]\nkeys = ["legal/**", "*.brand"]'.replace("\n", chr(10)))
    assert cfg.is_skipped("legal", "terms")
    assert cfg.is_skipped("legal/eu", "x")
    assert cfg.is_skipped("app", "brand")
    assert not cfg.is_skipped("app", "title")


def test_source_regex_needs_source(tmp_path):
    cfg = _cfg(tmp_path, '[exclude]\nsource_regex = ["^https?://"]')
    assert cfg.is_skipped("app", "link", "https://example.com")
    assert not cfg.is_skipped("app", "link", "Open the link")
    assert not cfg.is_skipped("app", "link")


def test_bad_regex_and_unknown_key(tmp_path):
    with pytest.raises(ConfigError, match="not a valid regex"):
        _cfg(tmp_path, '[exclude]\nsource_regex = ["("]')
    with pytest.raises(ConfigError):
        _cfg(tmp_path, '[exclude]\nbogus = ["x"]')


def test_default_is_empty(tmp_path):
    cfg = _cfg(tmp_path, "")
    assert cfg.exclude_keys == () and cfg.exclude_source == ()
    assert not cfg.is_skipped("app", "x", "anything")
