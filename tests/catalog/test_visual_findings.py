"""Tests for visual findings ingest and validate --check-layout (ADR-27)."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest

from llm_localizator.catalog.review_queue import ReviewQueue
from llm_localizator.catalog.visual_findings import (
    VisualFindingsError,
    crawl_kind_to_reason,
    parse_finding,
)
from llm_localizator.ops.ingest_visual import op_ingest_visual
from llm_localizator.ops.types import IngestVisualRequest, ValidateRequest
from llm_localizator.ops.validate import op_validate
from llm_localizator.pipeline.validate import run_validation
from tests.pipeline.test_translate import setup_project


def _write_png(path: Path, width: int = 200, height: int = 80) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def test_parse_finding_rejects_bad_version() -> None:
    with pytest.raises(VisualFindingsError, match="schema_version"):
        parse_finding({
            "schema_version": 99,
            "locale": "pl",
            "screen": "lobby",
            "reason": "layout_overflow",
            "message": "x",
        })


def test_parse_finding_page_level_ticket_key() -> None:
    f = parse_finding({
        "schema_version": 1,
        "locale": "pl",
        "screen": "lobby",
        "reason": "layout_overflow",
        "message": "clipped",
    })
    assert f.ticket_namespace() == "_visual"
    assert f.ticket_key() == "@lobby"


def test_parse_finding_accepts_layout_overlap() -> None:
    f = parse_finding({
        "schema_version": 1,
        "locale": "ar",
        "screen": "lobby",
        "reason": "layout_overlap",
        "message": "two labels share the same pixels",
        "selector": "span.title ∩ span.badge",
    })
    assert f.reason == "layout_overlap"
    assert f.selector == "span.title ∩ span.badge"


def test_crawl_kind_maps_to_findings_reason() -> None:
    assert crawl_kind_to_reason("clipped") == "layout_clip"
    assert crawl_kind_to_reason("offscreen") == "layout_overflow"
    assert crawl_kind_to_reason("overlap") == "layout_overlap"
    assert crawl_kind_to_reason("unknown") is None


def test_ingest_visual_enqueues(tmp_path: Path, make_config) -> None:
    cfg = make_config(tmp_path)
    findings = tmp_path / ".visual_findings.jsonl"
    findings.write_text(
        json.dumps({
            "schema_version": 1,
            "locale": "pl",
            "screen": "lobby",
            "namespace": "nav",
            "key": "home",
            "reason": "layout_overflow",
            "message": "nav home overflows",
            "source": "browse-review",
            "screenshot": "screenshots/lobby.png",
        }, ensure_ascii=False)
        + "\n"
        + json.dumps({
            "schema_version": 1,
            "locale": "pl",
            "screen": "lobby",
            "namespace": "nav",
            "key": "home",
            "reason": "layout_overflow",
            "message": "duplicate",
            "source": "browse-review",
        }, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    result = op_ingest_visual(cfg, IngestVisualRequest(path=str(findings)))
    assert result.ok
    assert result.data["enqueued"] == 1
    assert result.data["skipped"] == 1
    tickets = ReviewQueue(cfg.review_root()).open_tickets("pl")
    assert len(tickets) == 1
    assert tickets[0].reason == "layout_overflow"
    assert tickets[0].key == "home"


def test_check_layout_validate_emits_v27(project_root, make_config, make_catalog) -> None:
    setup_project(
        project_root,
        {"short": "Hi"},
        existing={"short": "Zdecydowanie za długie"},
    )
    ctx = project_root / "context"
    ctx.mkdir()
    (ctx / "app.json").write_text(
        json.dumps({
            "short": {"note": "chip", "screen": "filters", "maxChars": 2},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_png(ctx / "screenshots" / "filters.png", 200, 80)
    cfg = make_config(project_root, context_dir=ctx)
    catalog = make_catalog(cfg)
    report = run_validation(cfg, catalog, locales=["pl"], check_layout=True)
    v28 = [f for f in report.findings if f.check == "V28"]
    assert v28
    assert any("max_chars" in f.message for f in v28)

    result = op_validate(cfg, ValidateRequest(locales=["pl"], check_layout=True))
    assert any(f.get("check") == "V28" for f in result.data["findings"])
