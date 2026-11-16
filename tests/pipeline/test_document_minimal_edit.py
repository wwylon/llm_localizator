"""Minimal-edit drafts for changed document sections (C-047, ADR-100)."""

from __future__ import annotations

from llm_localizator.pipeline.documents import draft_section_edits, translate_document
from llm_localizator.providers import CompletionRequest, NullProvider


def test_changed_section_gets_a_draft_and_nothing_is_written(tmp_path) -> None:
    source, target = tmp_path / "en.md", tmp_path / "pl.md"
    source.write_text("## A\n\nOne day.\n\n## B\n\nKeep.\n", encoding="utf-8")
    state: dict = {}
    translate_document(
        source, target, "pl", NullProvider(handler=lambda r: "## A\n\nJeden dzien.\n\n"),
        model="m", state=state, report=lambda _m: None,
    )
    assert state["0"]["src"].startswith("## A")
    written = target.read_text(encoding="utf-8")

    source.write_text("## A\n\nTwo days.\n\n## B\n\nKeep.\n", encoding="utf-8")
    seen: list[str] = []

    def handler(request: CompletionRequest) -> str:
        seen.append(request.prompt)
        return '{"text": "## A\\n\\nDwa dni.\\n"}'

    drafts = draft_section_edits(
        source, target, "pl", NullProvider(handler=handler), model="m", state=state,
    )
    assert [d["index"] for d in drafts] == [0]
    assert "One day." in seen[0] and "Two days." in seen[0] and "Jeden dzien." in seen[0]
    assert drafts[0]["draft"].startswith("## A")
    assert target.read_text(encoding="utf-8") == written


def test_no_draft_without_a_recorded_old_source(tmp_path) -> None:
    source, target = tmp_path / "en.md", tmp_path / "pl.md"
    source.write_text("## A\n\nNew.\n", encoding="utf-8")
    target.write_text("## A\n\nStare.\n", encoding="utf-8")
    state = {"0": {"src_sha": "old", "text": "## A\n\nStare.\n"}}
    assert draft_section_edits(source, target, "pl", NullProvider(handler=lambda r: "x"), model="m", state=state) == []
