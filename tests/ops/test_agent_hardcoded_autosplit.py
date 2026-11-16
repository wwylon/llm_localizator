"""V-002 / ADR-105: oversized hardcoded reports auto-split without --split."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.agent_hardcoded import op_agent_hardcoded
from llm_localizator.ops.types import AgentHardcodedRequest
from llm_localizator.scan.base import HardcodedString, ScanResult


def _fake_scanner(project_root: Path, note: str = ""):
    class FakeScanner:
        directive_aliases = None
        routing_note = note
        src_dirs: list[str] = []  # coverage_summary walks these; nothing to walk here

        def __init__(self):
            self.root = project_root

        def reset_tree(self):
            return None

        def iter_files(self):
            return []

    return FakeScanner()


def test_auto_split_when_hits_exceed_max(tmp_path, make_config, monkeypatch) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text('x = "hello"\n', encoding="utf-8")
    cfg = make_config(
        root=root,
        name="hc",
        scan_adapter="python",
        scan_src_dirs=["src"],
    )

    hits = [
        HardcodedString(text=f"msg-{i}", file="src/a.py", line=i + 1, reason="string", confidence="medium")
        for i in range(5)
    ]

    def fake_scan(scanner, limit, store):
        result = ScanResult(files_scanned=1, suppressed=0)
        result.hardcoded = hits
        return result, [root / "src" / "a.py"]

    monkeypatch.setattr("llm_localizator.ops.agent_hardcoded._scan_files", fake_scan)
    monkeypatch.setattr(
        "llm_localizator.ops.agent_hardcoded.scanner_from_config",
        lambda *a, **k: _fake_scanner(root, "note"),
    )
    monkeypatch.setattr(
        "llm_localizator.ops.agent_hardcoded._fingerprint",
        lambda *a, **k: "test-key",
    )

    out = op_agent_hardcoded(
        cfg,
        AgentHardcodedRequest(max_hits=2, budget_tokens=15000, catalogue_audit=False),
    )
    assert out.ok
    assert out.data.get("autoSplit") is True
    assert out.data.get("parts", 0) >= 2
    out_dir = Path(out.data["outDir"])
    assert (out_dir / "index.md").exists()


def test_json_format_does_not_auto_split(tmp_path, make_config, monkeypatch) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "src").mkdir()
    cfg = make_config(root=root, name="hc", scan_adapter="python", scan_src_dirs=["src"])
    hits = [
        HardcodedString(text=f"m{i}", file="src/a.py", line=i, reason="string", confidence="medium")
        for i in range(5)
    ]

    def fake_scan(scanner, limit, store):
        result = ScanResult(files_scanned=1, suppressed=0)
        result.hardcoded = hits
        return result, []

    monkeypatch.setattr("llm_localizator.ops.agent_hardcoded._scan_files", fake_scan)
    monkeypatch.setattr(
        "llm_localizator.ops.agent_hardcoded.scanner_from_config",
        lambda *a, **k: _fake_scanner(root),
    )
    monkeypatch.setattr(
        "llm_localizator.ops.agent_hardcoded._fingerprint",
        lambda *a, **k: "test-key",
    )
    out = op_agent_hardcoded(
        cfg,
        AgentHardcodedRequest(fmt="json", max_hits=2, catalogue_audit=False),
    )
    assert out.ok
    assert "autoSplit" not in out.data
    assert len(out.data.get("hits") or []) == 5
