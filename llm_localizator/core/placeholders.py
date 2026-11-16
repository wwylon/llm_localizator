"""Rename an ICU placeholder inside one message (C-038).

Brace-depth aware, like :mod:`.icu`: it renames ``{old}``, ``{old, number}``,
the driving variable of ``{old, plural, ...}`` and any of those nested in a
branch body. A branch body that is a single word (``one {File}``) is text, not a
placeholder, and is left alone. Other placeholder syntaxes (``%s``, ``{{x}}``)
are not touched.
"""

from __future__ import annotations

import re

from .icu import PLURAL_HEAD_RE

__all__ = ["rename_placeholder", "is_placeholder_name"]

_NAME_RE = re.compile(r"\w+")
_BARE_HEAD_RE = re.compile(r"^(\s*)(\w+)(\s*(?:,.*)?)$", re.DOTALL)


def is_placeholder_name(name: str) -> bool:
    """A valid ICU argument name or index."""
    return bool(name) and _NAME_RE.fullmatch(name) is not None


def _match(s: str, start: int) -> int:
    """Index of the ``}`` closing the ``{`` at ``start``, or -1."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _walk(s: str, old: str, new: str, inner_fn) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch != "{":
            out.append(ch)
            i += 1
            continue
        j = _match(s, i)
        if j < 0:
            out.append(s[i:])
            break
        out.append("{" + inner_fn(s[i + 1:j], old, new) + "}")
        i = j + 1
    return "".join(out)


def _rename_text(s: str, old: str, new: str) -> str:
    return _walk(s, old, new, _rename_inner)


def _rename_inner(inner: str, old: str, new: str) -> str:
    head = PLURAL_HEAD_RE.match(inner)
    if head:
        var = head.group(1)
        prefix = inner[: head.start(1)] + (new if var == old else var) + inner[head.end(1): head.end()]
        # Branch bodies are text contexts; only their braces are walked.
        return prefix + _walk(inner[head.end():], old, new, _rename_text_body)
    bare = _BARE_HEAD_RE.match(inner)
    if bare and bare.group(2) == old:
        return bare.group(1) + new + bare.group(3)
    return inner


def _rename_text_body(body: str, old: str, new: str) -> str:
    return _rename_text(body, old, new)


def rename_placeholder(text: str, old: str, new: str) -> str:
    """Return ``text`` with placeholder ``old`` renamed to ``new``."""
    if not is_placeholder_name(old) or not is_placeholder_name(new):
        raise ValueError("placeholder names must be word characters")
    return _rename_text(text, old, new)
