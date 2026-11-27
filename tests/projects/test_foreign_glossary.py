"""Cross-domain glossary selection for live scoring (audit T5)."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.projects.context import foreign_glossary_for


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_foreign_glossary_excludes_own_domains(tmp_path: Path) -> None:
    root = tmp_path / "glossary"
    _write(root / "global.json", {"terms": {"App": {"pl": "Aplikacja"}}})
    _write(root / "ui.json", {"terms": {"Save": {"pl": "Zapisz"}}})
    _write(root / "poker.json", {"terms": {"bid": {"pl": "licytacja"}}})
    foreign = foreign_glossary_for(root, own_domains=["ui"])
    assert foreign is not None
    assert "bid" in foreign["terms"]
    assert "Save" not in foreign["terms"]
    assert "App" not in foreign["terms"]  # global is never foreign


def test_foreign_glossary_none_when_all_domains(tmp_path: Path) -> None:
    root = tmp_path / "glossary"
    _write(root / "ui.json", {"terms": {"Save": {"pl": "Zapisz"}}})
    assert foreign_glossary_for(root, own_domains=None) is None
    assert foreign_glossary_for(tmp_path / "missing", own_domains=["ui"]) is None
