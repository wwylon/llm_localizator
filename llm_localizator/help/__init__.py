"""Packaged guides: ``human.md`` for operators, ``agent.md`` for AI agents (ADR-121).

One source, three ways in: ``llm-localizator help human|agent``, the MCP resources
``llm-localizator://help/<name>``, and ``llm-localizator skill install`` (agent guide as a
Claude skill in a consumer repo).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "HELP_DIR",
    "GUIDES",
    "guide_path",
    "guide_text",
    "agent_steps",
    "format_agent_steps",
]

HELP_DIR = Path(__file__).resolve().parent
GUIDES = ("human", "agent")

_SECTION = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)


def guide_path(name: str) -> Path:
    if name not in GUIDES:
        raise ValueError(f"unknown guide {name!r} ({'|'.join(GUIDES)})")
    return HELP_DIR / f"{name}.md"


def guide_text(name: str) -> str:
    return guide_path(name).read_text(encoding="utf-8")


def agent_steps(text: str | None = None) -> list[tuple[int, str]]:
    """Ordered ``(n, title)`` from ``## N. Title`` headings in the agent guide (ADR-159)."""
    raw = text if text is not None else guide_text("agent")
    steps = [(int(m.group(1)), m.group(2).strip()) for m in _SECTION.finditer(raw)]
    steps.sort(key=lambda row: row[0])
    return steps


def format_agent_steps(steps: list[tuple[int, str]] | None = None) -> str:
    """One numbered line per step for ``help agent --print-steps``."""
    rows = steps if steps is not None else agent_steps()
    return "\n".join(f"{n}. {title}" for n, title in rows) + ("\n" if rows else "")
