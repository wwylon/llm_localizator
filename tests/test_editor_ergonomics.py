"""Spell check and history diff in the editor (C-046). Source-level guards."""

from __future__ import annotations

from pathlib import Path

JS = (Path(__file__).resolve().parent.parent / "llm_localizator" / "web" / "static" / "editor.js").read_text(encoding="utf-8")


def test_every_target_textarea_has_lang_and_spellcheck() -> None:
    for marker in ('area.id = "translation-field";', 'area.id = "plural-" + name;', 'area.className = "cell-edit";'):
        start = JS.index(marker)
        assert "area.spellcheck = true" in JS[start:start + 260], marker
        assert "area.lang = state.locale" in JS[start:start + 260], marker


def test_history_events_show_word_diff_and_toggle() -> None:
    body = JS[JS.index("function paintHistory"):JS.index("function paintDiff")]
    assert "diffToggle(" in body and "diffInto(" in body and "history-meta" in body
