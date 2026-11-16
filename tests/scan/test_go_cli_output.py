"""In a Go CLI project (go.mod requires cobra / urfave cli / kong), what it prints is UI text (B3, B23)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan import build_scanner

_SRC = '''package cmd

import (
	"fmt"
	"log"
)

func show(issue Issue) {
	fmt.Printf("# Agent Session for %s\\n\\n", issue.Identifier)
	fmt.Println("- **Status**: delegated (session not started)")
	output.Error("Not authenticated. Run 'linctl auth' first.", plaintext, jsonOut)
	output.Info(fmt.Sprintf("No agent delegation found for %s", issue.Identifier), plaintext, jsonOut)
	label := color.New(color.FgYellow).Sprint("Delegate:")
	log.Printf("debug: cache size %d", 3)
	key := fmt.Sprintf("%s-%s", a, b)
}
'''


def _hits(tmp_path: Path, gomod: str | None) -> dict[str, str]:
    (tmp_path / "cmd").mkdir()
    (tmp_path / "cmd" / "show.go").write_text(_SRC, encoding="utf-8")
    if gomod is not None:
        (tmp_path / "go.mod").write_text(gomod, encoding="utf-8")
    return {" ".join(h.text.split()): h.confidence for h in build_scanner("source", tmp_path, ["."]).scan().hardcoded}


def test_cli_output_is_ui(tmp_path: Path) -> None:
    hits = _hits(tmp_path, "module x\n\nrequire github.com/spf13/cobra v1.8.0\n")
    gate = {t for t, c in hits.items() if c in ("high", "medium")}
    for want in ("Agent Session for", "Not authenticated. Run 'linctl auth' first.", "No agent delegation found for"):
        assert any(want in t for t in gate), (want, sorted(gate))
    assert not any("debug: cache size" in t for t in gate)
    assert "%s-%s" not in gate


def test_library_output_stays_low(tmp_path: Path) -> None:
    hits = _hits(tmp_path, "module x\n")
    assert not {t for t, c in hits.items() if c in ("high", "medium") and "Not authenticated" in t}
