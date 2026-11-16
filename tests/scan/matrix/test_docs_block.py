"""docs/scanners.md carries the generated support matrix; it must match the code."""

from __future__ import annotations

from .docs_block import BEGIN, DOC, END, render_block


def test_support_matrix_block_is_current() -> None:
    text = DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert BEGIN in text and END in text, "run: python -m tests.scan.matrix.docs_block"
    current = text.split(BEGIN, 1)[1].split(END, 1)[0]
    assert BEGIN + current + END == render_block(), "stale: run python -m tests.scan.matrix.docs_block"
