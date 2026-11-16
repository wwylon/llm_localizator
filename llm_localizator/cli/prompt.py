"""Terminal prompting shared by the guided commands."""

from __future__ import annotations

import sys

__all__ = ["PromptAborted", "is_interactive", "read_line"]


class PromptAborted(Exception):
    """The user ended input (Ctrl-D / Ctrl-C) or there is nobody to answer."""


def is_interactive() -> bool:
    """True only when a person can see and answer prompts.

    Both ends must be terminals: on Windows a NUL stdin also reports as a tty,
    and prompting into a pipe helps nobody.
    """
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def read_line(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        print()
        raise PromptAborted from exc
