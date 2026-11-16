"""ICU message-format parsing: placeholders and plural categories.

Extraction is **brace-depth aware, not a flat regex**. A naive ``\\{(\\w+)\\}``
scan misidentifies a single-word plural branch body (e.g. Arabic ``two {عضوان}``
-- one token, no spaces) as if it were its own placeholder, because Python's
``\\w`` matches any Unicode letter. We instead walk the string and only look at
*top-level* brace groups (proper nesting depth), so branch bodies of a
``{var, plural, ...}`` clause are never mistaken for sibling placeholders.

The invariant, stated once:

  A top-level ``{...}`` span contributes a placeholder name if either
    (a) it matches ``^\\s*(\\w+)\\s*,\\s*(plural|select|selectordinal)\\s*,`` --
        in which case the *driving variable* (group 1) is the placeholder, and
        nothing inside the branch bodies counts; or
    (b) it matches a typed argument ``name, type[, style]`` (number/date/time/…);
    (c) its entire inner text is a bare identifier (``re.fullmatch(r"\\w+")``).
  Anything else contributes nothing.

Do not "simplify" this to a regex. The Arabic case above is a real regression
that a flat scan reintroduces silently.
"""

from __future__ import annotations

import re
from functools import lru_cache

__all__ = [
    "top_level_brace_spans",
    "bare_placeholder_spans",
    "is_bare_placeholder_span",
    "split_top_level_segments",
    "needs_icu_decomposition",
    "extract_placeholders",
    "extract_plural_categories",
    "satisfied_categories",
    "EXPLICIT_VALUE_EQUIVALENTS",
    "PLURAL_HEAD_RE",
]

PLURAL_HEAD_RE = re.compile(r"^\s*(\w+)\s*,\s*(plural|select|selectordinal)\s*,", re.DOTALL)
# ``{amount, number}``, ``{d, date, short}``, ``{t, time}`` — typed args whose
# name must survive translation (placeholder gate + mask).
_TYPED_ARG_RE = re.compile(r"^\s*(\w+)\s*,\s*(\w+)(?:\s*,.*)?$", re.DOTALL)
_TYPED_ARG_KINDS = frozenset({
    "number", "date", "time", "duration", "spellout", "ordinal", "relative",
})
_PLURAL_CATEGORY_RE = re.compile(
    r"(?:(zero|one|two|few|many|other)(?!\w)|=(\d+))\s*\{"
)
_PLURAL_BODY_RE = re.compile(r"^\s*\w+\s*,\s*(?:plural|selectordinal)\s*,(.*)$", re.DOTALL)
_BARE_IDENT_RE = re.compile(r"\w+")

# ICU allows explicit-value selectors (``=0``, ``=1``) alongside the CLDR
# plural-rule categories. An explicit ``=0`` branch is a *stronger* guarantee
# than the ``zero`` category -- it matches exactly zero, whereas ``zero`` is a
# grammatical class that in some languages covers other numbers too. So a
# translation using ``=0`` satisfies a requirement for ``zero``, and a checker
# that demands the named category anyway produces false positives on
# well-written messages.
EXPLICIT_VALUE_EQUIVALENTS: dict[str, str] = {"=0": "zero", "=1": "one"}


def top_level_brace_spans(s: str) -> list[str]:
    """Return each top-level ``{...}`` substring (braces included), honouring nesting."""
    spans: list[str] = []
    depth = 0
    start: int | None = None
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                spans.append(s[start : i + 1])
                start = None
    return spans


def _typed_arg_name(inner: str) -> str | None:
    """Driving name for ``{amount, number}`` / ``{d, date, short}``, else None."""
    if PLURAL_HEAD_RE.match(inner):
        return None
    m = _TYPED_ARG_RE.match(inner)
    if m and m.group(2).lower() in _TYPED_ARG_KINDS:
        return m.group(1)
    return None


def bare_placeholder_spans(s: str) -> list[tuple[int, int, str]]:
    """Return ``(start, end, span)`` for each top-level bare or typed arg token."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    for span in top_level_brace_spans(s):
        idx = s.find(span, pos)
        if idx < 0:
            continue
        inner = span[1:-1]
        if PLURAL_HEAD_RE.match(inner):
            pos = idx + len(span)
            continue
        stripped = inner.strip()
        if _BARE_IDENT_RE.fullmatch(stripped) or _typed_arg_name(inner):
            out.append((idx, idx + len(span), span))
        pos = idx + len(span)
    return out


def is_bare_placeholder_span(span: str) -> bool:
    """True when *span* is exactly one top-level bare ``{name}`` token."""
    bare = bare_placeholder_spans(span)
    return len(bare) == 1 and bare[0][2] == span


def split_top_level_segments(s: str) -> list[tuple[str, str]]:
    """Split *s* into alternating ``('text', ...)`` and ``('icu', ...)`` parts."""
    segments: list[tuple[str, str]] = []
    pos = 0
    for span in top_level_brace_spans(s):
        idx = s.find(span, pos)
        if idx < 0:
            continue
        if idx > pos:
            segments.append(("text", s[pos:idx]))
        segments.append(("icu", span))
        pos = idx + len(span)
    if pos < len(s):
        segments.append(("text", s[pos:]))
    return segments


def needs_icu_decomposition(s: str) -> bool:
    """True when a string should be translated span-by-span, not whole."""
    spans = top_level_brace_spans(s)
    if not spans:
        return False
    if len(spans) > 1:
        return True
    return bool(PLURAL_HEAD_RE.match(spans[0][1:-1]))


def extract_placeholders(s: str) -> set[str]:
    """Return the set of ICU placeholder names in ``s``.

    For a plural/select clause only the driving variable is returned; branch
    bodies are not scanned (see module docstring).
    """
    return set(_extract_placeholders_cached(s))


@lru_cache(maxsize=4096)
def _extract_placeholders_cached(s: str) -> frozenset[str]:
    placeholders: set[str] = set()
    for span in top_level_brace_spans(s):
        inner = span[1:-1]
        m = PLURAL_HEAD_RE.match(inner)
        if m:
            placeholders.add(m.group(1))
            continue
        typed = _typed_arg_name(inner)
        if typed:
            placeholders.add(typed)
            continue
        stripped = inner.strip()
        if _BARE_IDENT_RE.fullmatch(stripped):
            placeholders.add(stripped)
    return frozenset(placeholders)


def extract_plural_categories(s: str) -> set[str] | None:
    """Return the ICU plural selectors present, or ``None`` if not a plural string.

    Named CLDR categories come back bare (``"one"``); explicit-value selectors
    come back with their sign (``"=0"``). Use :func:`satisfied_categories` to
    compare against a requirement.
    """
    cached = _extract_plural_categories_cached(s)
    if cached is None:
        return None
    return set(cached)


def _blank_branch_bodies(body: str) -> str:
    """Empty each top-level ``{...}`` so nested selectors are not mistaken for ours."""
    out: list[str] = []
    depth = 0
    for ch in body:
        if ch == "{":
            if depth == 0:
                out.append("{")
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                out.append("}")
        elif depth == 0:
            out.append(ch)
    return "".join(out)


@lru_cache(maxsize=4096)
def _extract_plural_categories_cached(s: str) -> frozenset[str] | None:
    for span in top_level_brace_spans(s):
        inner = span[1:-1]
        m = _PLURAL_BODY_RE.match(inner)
        if m:
            found: set[str] = set()
            for named, explicit in _PLURAL_CATEGORY_RE.findall(_blank_branch_bodies(m.group(1))):
                found.add(named if named else f"={explicit}")
            return frozenset(found)
    return None


def satisfied_categories(found: set[str]) -> set[str]:
    """Expand explicit-value selectors into the categories they also satisfy.

    ``{"=0", "one", "other"}`` -> ``{"=0", "zero", "one", "other"}``.
    """
    out = set(found)
    for selector, category in EXPLICIT_VALUE_EQUIVALENTS.items():
        if selector in found:
            out.add(category)
    return out
