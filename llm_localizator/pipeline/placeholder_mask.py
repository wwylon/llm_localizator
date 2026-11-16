"""Mask bare ICU placeholders as numeric tokens before LLM translation.

Small models often drop or translate ``{players}``-style placeholders. Replacing
them with unique stand-in numbers (no braces) before the prompt and restoring
them afterward is more reliable than asking the model to preserve ICU syntax.
"""

from __future__ import annotations

import re

from ..core.dnt_spans import dnt_spans
from ..core.icu import bare_placeholder_spans

__all__ = [
    "mask_bare_placeholders",
    "restore_placeholders",
]

_TOKEN_BASE = 900_000_001
_DIGIT_RE = re.compile(r"\d+")


def _pick_tokens(text: str, count: int) -> list[str]:
    """Choose numeric tokens that do not already appear in *text*."""
    used = set(_DIGIT_RE.findall(text))
    tokens: list[str] = []
    n = _TOKEN_BASE
    while len(tokens) < count:
        tok = str(n)
        if tok not in used and tok not in tokens:
            tokens.append(tok)
        n += 1
    return tokens


def mask_bare_placeholders(text: str) -> tuple[str, dict[str, str]]:
    """Replace bare ``{name}`` placeholders with unique numeric stand-ins.

    Returns ``(masked_text, mapping)`` where mapping maps each token back to its
    original span (e.g. ``"900000001" -> "{players}"``). Plural/select clauses
    are left untouched.
    """
    marked = dnt_spans(text)
    # Marked elements (translate="no") are masked whole, so they come back byte for byte.
    # A bare placeholder inside one is part of that element, not a separate span.
    bare = [
        item for item in bare_placeholder_spans(text)
        if not any(s <= item[0] and item[1] <= e for s, e, _t in marked)
    ]
    bare = sorted([*bare, *marked], key=lambda item: item[0])
    if not bare:
        return text, {}

    tokens = _pick_tokens(text, len(bare))
    mapping: dict[str, str] = {}
    parts: list[str] = []
    last = 0
    for (start, end, span), tok in zip(bare, tokens):
        parts.append(text[last:start])
        parts.append(tok)
        mapping[tok] = span
        last = end
    parts.append(text[last:])
    return "".join(parts), mapping


def restore_placeholders(text: str, mapping: dict[str, str] | None) -> str:
    """Swap numeric stand-ins back to their original ``{name}`` spans."""
    if not mapping:
        return text
    out = text
    for tok in sorted(mapping, key=len, reverse=True):
        out = out.replace(tok, mapping[tok])
    return out
