"""The op result envelope documented in docs/agent-contract.md."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.types import OP_SCHEMA_VERSION, OpResult

DOC = Path(__file__).resolve().parents[2] / "docs" / "agent-contract.md"


def test_envelope_fields_and_version() -> None:
    out = OpResult(ok=True, exit_code=0, command="status", summary="s").to_dict()
    assert set(out) == {"schema_version", "ok", "exit_code", "command", "summary", "lines", "data"}
    assert out["schema_version"] == OP_SCHEMA_VERSION == 1


def test_doc_names_every_envelope_field_and_the_version() -> None:
    text = DOC.read_text(encoding="utf-8")
    for name in ("schema_version", "ok", "exit_code", "command", "summary", "lines", "data"):
        assert f"`{name}`" in text, name
    assert f'"schema_version": {OP_SCHEMA_VERSION}' in text
