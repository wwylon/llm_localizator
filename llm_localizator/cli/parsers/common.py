"""Shared argparse helpers and defaults for the CLI parsers."""

from __future__ import annotations

import argparse

from ...ops.types import parse_csv_list

#: Kept out of taskqueue's 8765/8766 range so both can run at once.
DEFAULT_WEB_PORT = 8770
DEFAULT_MARKETING_PORT = 8760


def _csv(value: str) -> list[str]:
    """Argparse type: comma-separated locales/namespaces."""
    return parse_csv_list(value) or []


def add_project_args(p: argparse.ArgumentParser) -> None:
    """Flags every project-scoped command shares (ADR-3 resolution order)."""
    p.add_argument("project", nargs="?", default=None,
                   help="Registered project name. Omit to discover .llm-localize.toml "
                        "by walking up from the current directory.")
    p.add_argument("--config", default=None, metavar="PATH",
                   help="Explicit path to a .llm-localize.toml, bypassing the registry.")
    p.add_argument("--branch", default=None, metavar="NAME",
                   help="Use the state and scores of a tracked branch (Branches page).")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number
