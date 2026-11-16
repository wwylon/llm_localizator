"""Per-key context fields: ``maxChars`` aliases."""

from __future__ import annotations

import json

import pytest

from llm_localizator.projects.context import ContextNotes


def _notes(tmp_path, entry) -> ContextNotes:
    (tmp_path / "app.json").write_text(json.dumps({"k": entry}), encoding="utf-8")
    return ContextNotes(tmp_path)


@pytest.mark.parametrize("field", ["maxChars", "maxLength", "max_length"])
def test_max_chars_aliases(tmp_path, field) -> None:
    assert _notes(tmp_path, {field: 12}).max_chars("app", "k") == 12


def test_max_chars_wins_over_aliases(tmp_path) -> None:
    notes = _notes(tmp_path, {"maxLength": 30, "maxChars": 12})
    assert notes.max_chars("app", "k") == 12


@pytest.mark.parametrize("bad", ["12", True, 1.5, None])
def test_max_chars_ignores_non_integers(tmp_path, bad) -> None:
    assert _notes(tmp_path, {"maxLength": bad}).max_chars("app", "k") is None


def test_stale_args_use_alias(tmp_path) -> None:
    notes = _notes(tmp_path, {"max_length": 9})
    assert notes.stale_args("app", "k")["max_chars"] == 9
