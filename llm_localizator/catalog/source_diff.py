"""Word-level difference between an old and a new source string (C-041, ADR-100).

Pure data: the editor colours it. A span on the new side with ``changed`` set is text that
the old translation does not yet cover, so it "needs translation". Whitespace is kept as its
own token so the spans join back into the exact strings.
"""

from __future__ import annotations

import difflib
import re

__all__ = ["diff_spans", "needs_translation"]

_TOKEN = re.compile(r"\s+|[^\s]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def diff_spans(old: str, new: str) -> list[dict]:
    """``[{op, old, new}]`` in reading order; ``op`` is equal, insert, delete or replace."""
    a, b = _tokens(old), _tokens(new)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        out.append({"op": tag, "old": "".join(a[i1:i2]), "new": "".join(b[j1:j2])})
    return out


def needs_translation(spans: list[dict]) -> list[dict]:
    """New-side spans in order, each flagged ``changed`` when the old translation lacks it."""
    return [
        {"text": s["new"], "changed": s["op"] in ("insert", "replace")}
        for s in spans if s["new"]
    ]
