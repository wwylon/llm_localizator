"""Tests for validate --write-flags (T-06)."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.ops.validate import write_flags as _write_flags
from llm_localizator.pipeline.validate import Finding, SEVERITY_WARNING, ValidationReport


def test_write_flags_appends_unique_v13(tmp_path: Path, make_config) -> None:
    flags = tmp_path / "flags.jsonl"
    flags.write_text(
        json.dumps({"locale": "pl", "namespace": "app", "key": "old", "reason": "prior"}) + "\n",
        encoding="utf-8",
    )
    cfg = make_config(tmp_path, flags_path=flags)
    report = ValidationReport(
        findings=[
            Finding("V13", SEVERITY_WARNING, "pl", "app", "old", "dup", None),
            Finding("V13", SEVERITY_WARNING, "ar", "play", "board", "missing approved", None),
            Finding("V06", SEVERITY_WARNING, "pl", "app", "x", "identical", None),
        ]
    )
    n = _write_flags(cfg, report, {"V13"})
    assert n == 1
    rows = [json.loads(l) for l in flags.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 2
    assert rows[1]["key"] == "board"
    assert rows[1]["reason"].startswith("V13:")
