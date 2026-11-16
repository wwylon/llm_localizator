"""C-035: context tags and --tag runs."""

from __future__ import annotations

import json

from llm_localizator.ops.tags import apply_tags
from llm_localizator.ops.types import TranslateRequest
from llm_localizator.projects.context import (
    ContextNotes,
    normalize_tags,
    write_context_entry,
)


class _Cfg:
    def __init__(self, d):
        self.context_dir = d


def test_normalize():
    assert normalize_tags("Checkout, legal ,checkout") == ["checkout", "legal"]
    assert normalize_tags(["A B", ""]) == ["a-b"]
    assert normalize_tags(None) == []


def test_write_and_lookup(tmp_path):
    write_context_entry(tmp_path, "app", "title", {"tags": ["checkout"]})
    write_context_entry(tmp_path, "app", "pay", {"tags": ["checkout", "legal"]})
    write_context_entry(tmp_path, "app", "other", {"note": "x"})
    notes = ContextNotes(tmp_path)
    assert notes.tags("app", "pay") == ["checkout", "legal"]
    assert notes.keys_with_tags(["legal"]) == ["app.pay"]
    assert notes.keys_with_tags(["checkout"]) == ["app.pay", "app.title"]
    write_context_entry(tmp_path, "app", "pay", {"tags": []})
    assert "pay" not in json.loads((tmp_path / "app.json").read_text())


def test_apply_tags_resolves_and_intersects(tmp_path):
    write_context_entry(tmp_path, "app", "a", {"tags": ["x"]})
    write_context_entry(tmp_path, "app", "b", {"tags": ["x"]})
    cfg = _Cfg(tmp_path)
    req, early = apply_tags(cfg, TranslateRequest(tags=["x"]), "translate")
    assert early is None and req.keys == ["app.a", "app.b"] and req.tags is None
    req, _ = apply_tags(cfg, TranslateRequest(tags=["x"], keys=["app.b", "app.z"]), "translate")
    assert req.keys == ["app.b"]


def test_no_match_is_noop(tmp_path):
    _req, early = apply_tags(_Cfg(tmp_path), TranslateRequest(tags=["nope"]), "translate")
    assert early is not None and early.ok and "nope" in early.summary


def test_tags_do_not_change_fingerprint_inputs(tmp_path):
    from llm_localizator.catalog.state import context_fingerprint

    write_context_entry(tmp_path, "app", "a", {"note": "n"})

    def fp():
        n = ContextNotes(tmp_path)
        return context_fingerprint(n.note("app", "a"), n.screen("app", "a"), n.max_chars("app", "a"))

    before = fp()
    write_context_entry(tmp_path, "app", "a", {"tags": ["x"]})
    assert fp() == before
