"""``documents --draft-edits`` prints minimal-edit drafts and writes nothing (C-052)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from llm_localizator.cli import cmd_documents as docs_mod
from llm_localizator.cli.cmd_documents import _print_edit_drafts
from llm_localizator.pipeline.documents import translate_document
from llm_localizator.providers import NullProvider


def test_draft_edits_prints_a_diff_and_leaves_files_alone(tmp_path, capsys, monkeypatch) -> None:
    doc_dir = tmp_path / "docs"
    (doc_dir / "en").mkdir(parents=True)
    (doc_dir / "pl").mkdir()
    source, target = doc_dir / "en" / "terms.md", doc_dir / "pl" / "terms.md"
    source.write_text("## A\n\nOne day.\n", encoding="utf-8")
    state: dict = {}
    translate_document(
        source, target, "pl", NullProvider(handler=lambda r: "## A\n\nJeden dzien.\n\n"),
        model="m", state=state, report=lambda _m: None,
    )
    state_path = doc_dir / ".state" / "pl.json"
    state_path.parent.mkdir()
    state_path.write_text(json.dumps({"terms": state}), encoding="utf-8")
    source.write_text("## A\n\nTwo days.\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    # Stand-in config: state beside the documents, as ProjectConfig.documents_state_root does with data_home="project".
    cfg = SimpleNamespace(
        documents_state_dir=None,
        model_for=lambda _l: "m",
        documents_state_root=lambda d=None: (d or doc_dir) / ".state",
    )
    monkeypatch.setattr(
        docs_mod,
        "project_provider",
        lambda _c: NullProvider(handler=lambda r: '{"text": "## A\\n\\nDwa dni.\\n"}'),
    )
    assert _print_edit_drafts(cfg, doc_dir, doc_dir / "en", ["terms"], ["pl"], "m") == 0

    out = capsys.readouterr().out
    assert "pl/terms section 0" in out and "+Dwa dni." in out and "1 draft(s)" in out
    assert target.read_text(encoding="utf-8") == before
