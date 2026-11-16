"""``"a " + x + " b"`` chains reported as one sentence (scanner v17, B4)."""

from __future__ import annotations

from llm_localizator.scan.base import ScanResult
from llm_localizator.scan.js_context import scan_js_literals

SRC = '''ctx.fillText("Game over " + score, 5, 5);
el.textContent = "Saved " + n + " files";
const msg = "Connection lost, retrying" + " in " + n + " seconds";
k = "Score: " + a + " / " + b;
call("Saved " + n, "Other text here");
'''


def test_chains_join_into_one_finding() -> None:
    r = ScanResult()
    scan_js_literals(SRC, "a.js", r)
    got = {(h.line, h.text) for h in r.hardcoded}
    assert (1, "Game over {…}") in got
    assert (2, "Saved {…} files") in got
    assert (3, "Connection lost, retrying in {…} seconds") in got
    assert (4, "Score: {…} / {…}") in got
    # Orphan pieces are not reported separately.
    assert not any(t.strip() in ("files", "seconds", "in") for _, t in got)
    # An argument list is not a + chain: the second argument is not glued on.
    assert not any("Other text here" in t and "Saved" in t for _, t in got)
