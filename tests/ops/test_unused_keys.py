"""C-022: validate --unused (V41)."""

from __future__ import annotations

from llm_localizator.ops.unused import unused_keys


def test_unused_basic_and_plural_base():
    cat = {"app": ["title", "item_one", "item_other", "gone", "dyn.a"]}
    used = {("app", "title"), ("app", "item")}
    assert unused_keys(cat, used, ["app/dyn.*"]) == [("app", "gone")]


def test_other_namespace_does_not_count():
    assert unused_keys({"a": ["k"]}, {("b", "k")}, []) == [("a", "k")]


def test_no_scanner_is_a_note(tmp_path):
    from llm_localizator.catalog import build_catalog
    from llm_localizator.ops.unused import find_unused
    from llm_localizator.projects.config import load_config

    nl = chr(10)
    p = tmp_path / ".llm-localize.toml"
    p.write_text(nl.join([
        "[project]", 'name = "demo"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "messages/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "",
    ]), encoding="utf-8")
    cfg = load_config(p)
    cat = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    findings, note = find_unused(cfg, cat, None)
    assert findings == [] and "V41 skipped" in note
