"""``llm-localizator mcp`` — stdio server. The protocol package is optional."""

from __future__ import annotations

from ..mcp.server import main

__all__ = ["run"]


def run(args) -> int:
    del args
    return main()
