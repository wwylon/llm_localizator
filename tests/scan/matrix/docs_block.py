"""The generated support matrix in docs/scanners.md.

    python -m tests.scan.matrix.docs_block        # rewrite the block between the markers

``test_docs_block.py`` fails when the committed block differs from what this renders, so the docs cannot drift
from the registry, the tier table or the conformance matrix.
"""

from __future__ import annotations

from pathlib import Path

from llm_localizator.core.languages import source_languages
from llm_localizator.scan.base import UNSUPPORTED_UI_EXTENSIONS
from llm_localizator.scan.tiers import tier_for

from .runner import scores
from .spec import LANGS

BEGIN = "<!-- support-matrix:begin -->"
END = "<!-- support-matrix:end -->"
DOC = Path(__file__).resolve().parents[3] / "docs" / "scanners.md"


def render_block() -> str:
    table = scores()
    lines = [
        BEGIN,
        "| Language | Extensions | Detector | Tier | Conformance matrix |",
        "|---|---|---|---|---|",
    ]
    for lang in sorted(source_languages(), key=lambda row: row.id):
        cells = table.get(lang.id, {}).get("cells")
        if cells:
            ok = sum(c["ok"] for c in cells.values())
            matrix = f"{ok}/{len(cells)} cells"
        else:
            matrix = "n/a"
        exts = " ".join(f"`{e}`" for e in lang.extensions)
        lines.append(f"| {lang.id} | {exts} | {lang.detector} | {tier_for(lang.id)} | {matrix} |")
    lines.append(f"| not scanned | {' '.join(f'`{e}`' for e in sorted(UNSUPPORTED_UI_EXTENSIONS))} | none | reported-only | n/a |")
    lines.append(END)
    return "\n".join(lines)


def update_docs() -> bool:
    text = DOC.read_text(encoding="utf-8")
    crlf = "\r\n" in text
    text = text.replace("\r\n", "\n")
    block = render_block()
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _old, tail = rest.split(END, 1)
        new = head + block + tail
    else:
        marker = "## Usage artefacts"
        new = text.replace(marker, f"### Support matrix (generated)\n\n{block}\n\n{marker}", 1)
    changed = new != text
    DOC.write_text(new.replace("\n", "\r\n") if crlf else new, encoding="utf-8", newline="")
    return changed


if __name__ == "__main__":
    print("updated" if update_docs() else "already current")
