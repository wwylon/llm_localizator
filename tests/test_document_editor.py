"""Hybrid legal section pack/save (ADR-109)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.web.document_editor import (
    doc_namespace,
    pack_collection_file,
    save_collection_section,
)
from llm_localizator.web.server_logic import build_state


def _seed_legal(root: Path) -> None:
    en = root / "content" / "legal" / "en"
    pl = root / "content" / "legal" / "pl"
    en.mkdir(parents=True)
    pl.mkdir(parents=True)
    (en / "terms.md").write_text(
        "## Intro\n\nHello terms.\n\n## Privacy\n\nPrivate bits.\n",
        encoding="utf-8",
    )
    (pl / "terms.md").write_text(
        "## Intro\n\nWitaj terms.\n\n## Privacy\n\nPrywatne.\n",
        encoding="utf-8",
    )


def test_doc_namespace_is_stable() -> None:
    assert doc_namespace("legal", "terms.md") == "doc:legal/terms.md"
    assert doc_namespace("legal", "bridge/help.md") == "doc:legal/bridge/help.md"


def test_pack_collection_file_splits_sections(tmp_path, make_config) -> None:
    _seed_legal(tmp_path)
    cfg = make_config(tmp_path, documents_dir=tmp_path / "content" / "legal")
    payload = pack_collection_file(cfg, "legal", "pl", "terms.md")
    assert payload["path"] == "terms.md"
    assert payload["namespace"] == "doc:legal/terms.md"
    assert len(payload["sections"]) == 2
    assert payload["sections"][0]["heading"] == "Intro"
    assert "Hello terms" in payload["sections"][0]["source"]
    assert "Witaj" in payload["sections"][0]["target"]
    assert payload["sections"][1]["heading"] == "Privacy"
    assert payload["sections"][0]["key"] == "0"
    assert payload["preview"]


def test_save_collection_section_rewrites_and_history(tmp_path, make_config) -> None:
    _seed_legal(tmp_path)
    cfg = make_config(tmp_path, documents_dir=tmp_path / "content" / "legal")
    st = build_state(cfg)
    result = save_collection_section(
        st, "legal", "pl", "terms.md", 0, "## Intro\n\nZmienione.\n\n",
    )
    assert result["ok"] is True
    assert result["namespace"] == "doc:legal/terms.md"
    text = (tmp_path / "content" / "legal" / "pl" / "terms.md").read_text(encoding="utf-8")
    assert "Zmienione" in text
    assert "Prywatne" in text
    events = st.history.events_for("pl", "doc:legal/terms.md", "0")
    assert events and "Zmienione" in (events[-1].next or "")
    state_path = tmp_path / "content" / "legal" / ".state" / "pl.json"
    assert state_path.is_file()
    assert '"0"' in state_path.read_text(encoding="utf-8")
