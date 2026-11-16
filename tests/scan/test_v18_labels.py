"""Scanner v18: knob names and lowercase phrases in label tags, wrapped prose with "; " (B4)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan.base import ScanResult
from llm_localizator.scan.next_intl import NextIntlScanner

TSX = """export function A({ isToy }: { isToy: boolean }) {
  return (
    <div>
      {isToy && (
        <p className="hint toy-note">
          Toy variant: stack/blinds hidden; opponent picker limited to Toy + Baselines.
        </p>
      )}
      <label className="field-label">raise to (total, this street)</label>
      <span className="label">master_seed</span>
      <span className="mono">deck_seed</span>
      <option>fast_mode</option>
      <p>for (let i = 0; i < n; i++) x;</p>
    </div>
  );
}
"""


def test_v18_rules(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    path = tmp_path / "src" / "A.tsx"
    path.write_text(TSX, encoding="utf-8")
    result = ScanResult()
    NextIntlScanner(tmp_path, ["src"]).scan_file(path, TSX.splitlines(), result)
    got = {h.text for h in result.hardcoded}
    assert "raise to (total, this street)" in got
    assert "master_seed" in got
    assert "Toy variant: stack/blinds hidden; opponent picker limited to Toy + Baselines." in got
    # snake_case outside a label position stays silent: ids, option values.
    assert "deck_seed" not in got and "fast_mode" not in got
    assert not any(t.startswith("for (") for t in got)
