"""C-041: source-diff and minimal-edit drafts (ADR-100)."""

from __future__ import annotations

import json

from llm_localizator.catalog.drafts import DraftStore
from llm_localizator.catalog.source_diff import diff_spans, needs_translation
from llm_localizator.catalog.source_history import SourceHistory
from llm_localizator.ops.draft import op_draft
from llm_localizator.ops.source_diff import op_source_diff
from llm_localizator.ops.types import DraftRequest
from llm_localizator.pipeline.minimal_edit import build_minimal_edit_prompt, parse_minimal_edit
from llm_localizator.projects.config import load_config


def _cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))
    for loc, text in (("en", "Pay within 30 days"), ("de", "Zahlen Sie innerhalb von 14 Tagen")):
        d = tmp_path / "m" / loc
        d.mkdir(parents=True)
        (d / "app.json").write_text(json.dumps({"terms": text}), encoding="utf-8")
    (tmp_path / ".llm-localize.toml").write_text("\n".join([
        "[project]", 'name = "demo"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "m/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "",
    ]), encoding="utf-8")
    return load_config(tmp_path / ".llm-localize.toml")


def test_spans_flag_only_the_changed_words():
    spans = diff_spans("Pay within 14 days", "Pay within 30 days")
    marked = needs_translation(spans)
    assert "".join(s["text"] for s in marked) == "Pay within 30 days"
    assert [s["text"] for s in marked if s["changed"]] == ["30"]
    assert diff_spans("same", "same") == [{"op": "equal", "old": "same", "new": "same"}]


def test_source_diff_reads_the_log(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    none = op_source_diff(cfg, "de", "app", "terms")
    assert none.ok and none.data["changed"] is False
    SourceHistory(cfg.state_root()).record_changes([("app", "terms", "Pay within 14 days", "Pay within 30 days")])
    res = op_source_diff(cfg, "de", "app", "terms")
    assert res.data["changed"] and res.data["oldSource"] == "Pay within 14 days"
    assert res.data["translation"].startswith("Zahlen")
    assert [s["text"] for s in res.data["newSpans"] if s["changed"]] == ["30"]
    assert not op_source_diff(cfg, "xx", "app", "terms").ok
    assert not op_source_diff(cfg, "de", "", "").ok


def test_minimal_edit_prompt_carries_all_three_texts():
    p = build_minimal_edit_prompt("old en", "new en", "alt de", "German")
    assert "old en" in p and "new en" in p and "alt de" in p
    assert parse_minimal_edit('noise {"text": " neu "} tail') == "neu"
    assert parse_minimal_edit("not json") == ""


class _Fake:
    def __init__(self):
        self.prompts = []

    def complete(self, request):
        self.prompts.append(request.prompt)
        return '{"text": "Zahlen Sie innerhalb von 30 Tagen"}'


def test_minimal_edit_draft_is_stored_not_applied(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    req = DraftRequest(action="create", locale="de", namespace="app", key="terms", mode="minimal-edit")
    assert "recorded source change" in op_draft(cfg, req).summary
    SourceHistory(cfg.state_root()).record_changes([("app", "terms", "Pay within 14 days", "Pay within 30 days")])
    fake = _Fake()
    monkeypatch.setattr("llm_localizator.ops.source_diff.provider_for_locale", lambda *a, **k: fake)
    res = op_draft(cfg, req)
    assert res.ok, res.summary
    assert "Zahlen Sie innerhalb von 14 Tagen" in fake.prompts[0]
    entry = next(iter(DraftStore.for_project(cfg).items().values()))
    assert entry["text"].endswith("30 Tagen") and entry["source"] == "Pay within 30 days"
    on_disk = json.loads((tmp_path / "m" / "de" / "app.json").read_text(encoding="utf-8"))
    assert on_disk["terms"].endswith("14 Tagen")  # never applied


def test_unknown_draft_mode_is_refused(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    res = op_draft(cfg, DraftRequest(action="create", locale="de", namespace="app", key="terms", mode="bogus"))
    assert not res.ok
