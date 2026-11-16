import json
from pathlib import Path

from llm_localizator.projects.context import ContextNotes, write_context_entry


def test_write_context_entry_merges_llm_note(tmp_path: Path) -> None:
    ctx = tmp_path / "context"
    write_context_entry(ctx, "app", "title", {"note": "button label"})
    write_context_entry(ctx, "app", "title", {"llmNote": "keep it short"})
    notes = ContextNotes(ctx)
    assert notes.note("app", "title") == "button label"
    assert notes.llm_note("app", "title") == "keep it short"
    data = json.loads((ctx / "app.json").read_text(encoding="utf-8"))
    assert data["title"]["llmNote"] == "keep it short"
