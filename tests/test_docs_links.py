"""Relative links in the README and docs/*.md point at files that exist."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s]+)\)")
SKIP = ("http://", "https://", "mailto:", "#")


def _docs() -> list[Path]:
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def test_relative_markdown_links_resolve() -> None:
    broken: list[str] = []
    for doc in _docs():
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            if target.startswith(SKIP):
                continue
            path = target.split("#", 1)[0]
            if path and not (doc.parent / path).resolve().exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, "broken links:\n" + "\n".join(broken)
