"""Discover proposes collections and does not write config."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.projects.collections import (
    discover_collections,
    get_collection,
    list_collection_files,
    visible_collections,
)


def test_help_locales_propose_one_markdown_collection(tmp_path: Path) -> None:
    for locale in ("en", "pl"):
        path = tmp_path / "content" / "help" / locale / "bridge" / "intro.md"
        path.parent.mkdir(parents=True)
        path.write_text("# Intro\n", encoding="utf-8")
    vendor = tmp_path / "node_modules" / "en" / "readme.md"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("vendor", encoding="utf-8")
    (tmp_path / "node_modules" / "pl").mkdir()
    (tmp_path / "node_modules" / "pl" / "readme.md").write_text("vendor", encoding="utf-8")

    proposals = discover_collections(tmp_path)
    assert len(proposals) == 1
    item = proposals[0]
    assert item["name"] == "help"
    assert item["format"] == "markdown"
    assert item["root"] == "content/help"
    assert item["locales"] == ["en", "pl"]


def test_get_collection_configured_skips_discover(tmp_path, make_config, monkeypatch) -> None:
    """Hot paths must not walk the repo when the collection is in toml."""
    for locale in ("en", "pl"):
        legal = tmp_path / "content" / "legal" / locale
        legal.mkdir(parents=True)
        (legal / "terms.md").write_text("terms\n", encoding="utf-8")
    cfg = make_config(tmp_path, documents_dir=tmp_path / "content" / "legal")

    def boom(_root):
        raise AssertionError("discover_collections must not run for configured legal")

    monkeypatch.setattr(
        "llm_localizator.projects.collections.discover_collections", boom,
    )
    coll = get_collection(cfg, "legal")
    assert coll.name == "legal"
    assert coll.kind == "files"
    rows = list_collection_files(cfg, "legal", ["pl"])
    assert len(rows) == 1
    assert rows[0]["path"] == "terms.md"
    assert rows[0]["locales"]["pl"]["present"] is True


def test_unconfigured_help_is_visible_without_a_second_legal(tmp_path, make_config) -> None:
    for locale in ("en", "pl"):
        path = tmp_path / "content" / "help" / locale / "intro.md"
        path.parent.mkdir(parents=True)
        path.write_text("# Hi\n", encoding="utf-8")
        legal = tmp_path / "content" / "legal" / locale
        legal.mkdir(parents=True)
        (legal / "terms.md").write_text("terms\n", encoding="utf-8")
    cfg = make_config(tmp_path, documents_dir=tmp_path / "content" / "legal")
    names = [c.name for c in visible_collections(cfg)]
    assert "help" in names
    assert names.count("legal") == 1
    assert names.count("messages") == 1
    help_coll = next(c for c in visible_collections(cfg) if c.name == "help")
    assert help_coll.kind == "files"
    assert help_coll.format == "markdown"


def test_file_collection_ops_refuse_key_commands(tmp_path, make_config) -> None:
    for locale in ("en", "pl"):
        path = tmp_path / "content" / "help" / locale / "intro.md"
        path.parent.mkdir(parents=True)
        path.write_text("# Hi\n", encoding="utf-8")
    cfg = make_config(tmp_path)
    blocked = dispatch_op(cfg, "validate", {"collection": "help"}, actor_role="Admin")
    assert blocked["ok"] is False
    assert blocked["exit_code"] == 64
    assert "file collection" in blocked["summary"]
    status = dispatch_op(cfg, "status", {"collection": "help"}, actor_role="Admin")
    assert status["ok"] is True
    assert "1 file" in status["summary"]


def test_discover_prints_a_request_places_snippet_and_writes_nothing(tmp_path, make_config) -> None:
    for locale in ("en", "pl"):
        path = tmp_path / "content" / "help" / locale / "intro.md"
        path.parent.mkdir(parents=True)
        path.write_text("# Hi\n", encoding="utf-8")
    cfg = make_config(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    out = dispatch_op(cfg, "discover", {}, actor_role="Admin")
    snippet = out["data"]["places_snippet"]
    assert '[places."help"]' in snippet
    assert 'policy = "request"' in snippet
    assert sorted(p.name for p in tmp_path.iterdir()) == before
