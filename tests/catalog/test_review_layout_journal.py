"""Tests for review queue, layout QA, flush journal, embeddings TM."""

from __future__ import annotations

import struct
from pathlib import Path

from llm_localizator.catalog.embeddings import cosine, embed, semantic_overlap
from llm_localizator.catalog.flush_journal import FlushIntent, FlushJournal
from llm_localizator.catalog.review_queue import (
    STATUS_BLOCKED,
    STATUS_DONE,
    ReviewQueue,
)
from llm_localizator.catalog.tm import TranslationMemory
from llm_localizator.core.layout_qa import check_layout, png_dimensions
from llm_localizator.pipeline.context_assembler import assemble_context
from llm_localizator.projects.config import ProjectConfig, ProviderConfig


def test_review_queue_enqueue_and_comment(tmp_path: Path) -> None:
    q = ReviewQueue(tmp_path / ".llm-review")
    t = q.enqueue(
        locale="pl", namespace="ui", key="save",
        reason="needs_context:missing_note", status=STATUS_BLOCKED,
        source="Save",
    )
    assert t.id
    assert q.find_open("pl", "ui", "save") is not None
    assert q.add_comment("pl", t.id, "alice", "need screen shot")
    assert q.set_status("pl", t.id, STATUS_DONE)
    assert q.find_open("pl", "ui", "save") is None


def test_flush_journal_interrupted(tmp_path: Path) -> None:
    j = FlushJournal(tmp_path)
    j.begin(FlushIntent(
        run_id="abc", started_at="2026-01-01T00:00:00Z",
        locales=["pl"], pending_keys=2, phase="catalog",
    ))
    j.set_phase("state")
    left = j.interrupted()
    assert left is not None
    assert left.phase == "state"
    j.set_phase("done")
    j.clear()
    assert j.interrupted() is None


def test_png_dimensions_and_layout(tmp_path: Path) -> None:
    # Minimal valid PNG 1x1
    path = tmp_path / "a.png"
    # Write via struct: signature + IHDR chunk
    ihdr_data = struct.pack(">IIBBBBB", 80, 20, 8, 2, 0, 0, 0)
    import binascii

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr_data)
        + chunk(b"IEND", b"")
    )
    assert png_dimensions(path) == (80, 20)
    issues = check_layout(
        "Cancel", "Anuluj tę bardzo długą etykietę przycisku", "pl",
        max_chars=8, screenshot=path,
    )
    assert any(i.code == "max_chars" for i in issues)


def test_semantic_tm_near(tmp_path: Path) -> None:
    tm = TranslationMemory(tmp_path)
    tm.record(locale="pl", source="Cancel the action", text="Anuluj", model="m")
    tm.record(locale="pl", source="Completely unrelated", text="Inne", model="m")
    hits = tm.near("pl", "Cancel action", min_overlap=0.2, semantic=True, limit=5)
    assert hits
    assert hits[0][0].source == "Cancel the action"
    assert semantic_overlap("Cancel", "Cancel") > 0.9
    assert cosine(embed("ab"), embed("ab")) > 0.9


def test_assemble_blocks_high_risk_incomplete() -> None:
    pkg = assemble_context(
        source="Delete account permanently",
        locale="pl",
        namespace="acct",
        key="delete",
        context="",
        screen=None,
        high_risk=True,
    )
    assert pkg.incomplete
    cfg = ProjectConfig(
        root=Path("."), name="t", source_locale="en",
        catalog_format="json-nested",
        catalog_path="m/{locale}/{namespace}.json",
        targets=["pl"], models={"default": "m"},
        provider=ProviderConfig(kind="null"), domain="test",
    )
    from llm_localizator.pipeline.ensemble import risk_level

    level = risk_level(
        "Delete account permanently", cfg, context_incomplete=True,
    )
    assert level == "high"
