"""Packaged guides: ``human.md`` for operators, ``agent.md`` for AI agents (ADR-121).

One source, three ways in: ``llm-localizator help human|agent``, the MCP resources
``llm-localizator://help/<name>``, and ``llm-localizator skill install`` (agent guide as a
Claude skill in a consumer repo).
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["HELP_DIR", "GUIDES", "guide_path", "guide_text"]

HELP_DIR = Path(__file__).resolve().parent
GUIDES = ("human", "agent")


def guide_path(name: str) -> Path:
    if name not in GUIDES:
        raise ValueError(f"unknown guide {name!r} ({'|'.join(GUIDES)})")
    return HELP_DIR / f"{name}.md"


def guide_text(name: str) -> str:
    return guide_path(name).read_text(encoding="utf-8")
