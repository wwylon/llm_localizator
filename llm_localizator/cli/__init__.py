"""Command-line entry points.

Terminal setup (stdout encoding) happens in :mod:`llm_localizator.cli.main` and
nowhere else, so importing the library has no side effects.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    from .main import main as _main

    return _main(argv)
