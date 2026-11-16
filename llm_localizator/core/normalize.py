"""Deterministic clean-up of model output before validation (plan Part C, C2 / E6, E9).

Models wrap answers in quotes, write "..." where the source has "…", and change the
case of the first letter. Each of these used to cost a reject and a retry, and the
ones that slipped through stayed in catalogues. They have one right answer given the
source, so they are fixed here instead of being sent back to the model.

Pure: no I/O, no project knowledge. :func:`normalize_candidate` returns the cleaned
text and the names of the steps that changed it (``quotes``, ``icu_quotes``,
``ellipsis``, ``case``) so callers can report them.
"""

from __future__ import annotations

import re

from .locales import profile

__all__ = ["normalize_candidate", "NORMALIZE_STEPS"]

NORMALIZE_STEPS = ("first_line", "quotes", "icu_quotes", "plural_fill", "ellipsis", "symbol", "case")
#: "~{t}" spelled out by the model ("Około {t}") -> the symbol back (ADR-130).
_SYMBOL_WORDS = {
    "~": ("około", "ok.", "circa", "ca.", "etwa", "environ", "aprox.", "approx.", "about"),
    "≈": ("około", "ok.", "circa", "ca.", "etwa", "environ", "approx.", "about"),
}

# Opening quote -> the closing quotes that may pair with it.
_QUOTE_PAIRS: dict[str, str] = {
    '"': '"',
    "“": "”“",
    "”": "”",
    "„": "”“",
    "«": "»",
    "»": "«",
    "‘": "’",
    "‚": "‘’",
    "'": "'",
}
_DOUBLE_QUOTES = frozenset('"“”„«»')
_ICU_HEAD_RE = re.compile(r"\{\s*\w+\s*,\s*(?:plural|select|selectordinal)\s*,")
# A branch body that is nothing but one quoted phrase: `{"plik"}`, `{„plik”}`.
# Apostrophes are ICU escapes, so they are never treated as model quoting here.
_ICU_QUOTED_BRANCH_RE = re.compile(r"\{(\s*)([\"“„«»])([^{}\"“”„«»]*)([\"”“»«])(\s*)\}")
_TURKIC = frozenset({"tr", "az"})


def _base(locale: str) -> str:
    return (locale or "").replace("_", "-").split("-", 1)[0].lower()


def _strip_wrapper(source: str, text: str) -> str:
    """Remove one pair of quotes around the whole value when the source has none."""
    src = source.strip()
    if len(text) < 3 or (src and src[0] in _QUOTE_PAIRS):
        return text
    closers = _QUOTE_PAIRS.get(text[0])
    if not closers or text[-1] not in closers:
        return text
    inner = text[1:-1]
    # `"Open" or "Close"` is two quoted words, not one wrapped value.
    if text[0] in inner or text[-1] in inner:
        return text
    return inner.strip()


def _strip_icu_branch_quotes(source: str, text: str) -> str:
    if not _ICU_HEAD_RE.search(text) or any(ch in _DOUBLE_QUOTES for ch in source):
        return text
    return _ICU_QUOTED_BRANCH_RE.sub(
        lambda m: "{" + m.group(1) + m.group(3) + m.group(5) + "}"
        if m.group(4) in _QUOTE_PAIRS.get(m.group(2), "") else m.group(0),
        text,
    )


def _upper(ch: str, base: str) -> str:
    if base in _TURKIC:
        return {"i": "İ", "ı": "I"}.get(ch, ch.upper())
    return ch.upper()


def _lower(ch: str, base: str) -> str:
    if base in _TURKIC:
        return {"I": "ı", "İ": "i"}.get(ch, ch.lower())
    return ch.lower()


def _first_word(text: str) -> str:
    m = re.match(r"[^\W\d_]+", text)
    return m.group(0) if m else ""


def _match_case(source: str, text: str, locale: str) -> str:
    """The first letter follows the source: "Save" -> "Zapisz", "and 3 more" -> "i 3 więcej"."""
    src, out = source.lstrip(), text
    lead = len(out) - len(out.lstrip())
    body = out[lead:]
    if not src or not body or not src[0].isalpha() or not body[0].isalpha():
        return text
    base = _base(locale)
    src_word, out_word = _first_word(src), _first_word(body)
    if src[0].isupper() and body[0].islower():
        return out[:lead] + _upper(body[0], base) + body[1:]
    if (
        src_word.islower()
        and body[0].isupper()
        # "Ziarno" and "I {n}" yes, "URL" / "iOS" / a bare "A" no.
        and (out_word[1:].islower() if len(out_word) > 1 else len(body) > 1)
        and not profile(locale).capitalizes_nouns
    ):
        return out[:lead] + _lower(body[0], base) + body[1:]
    return text


_EXPLANATION = re.compile(r"^(?:\(|\[|\*|-|—|–|(?:note|explanation|translation|uwaga|"
                          r"alternatively|or|lub)\b)", re.I)
_PLURAL_HEAD = re.compile(r"\{\s*(\w+)\s*,\s*plural\s*,")


def _plural_branches(text: str, start: int) -> tuple[int, dict[str, tuple[int, int]]] | None:
    """For the plural opening at ``start``: (end, {category: (body_start, body_end)})."""
    i = text.index(",", text.index(",", start) + 1) + 1
    branches: dict[str, tuple[int, int]] = {}
    while i < len(text):
        m = re.compile(r"\s*(=?\w+)\s*\{").match(text, i)
        if not m:
            end = text.find("}", i)
            return (end + 1, branches) if end >= 0 and not text[i:end].strip() else None
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        if depth:
            return None
        branches[m.group(1)] = (m.end(), j - 1)
        i = j
    return None


def _fill_plural_categories(out: str, locale: str) -> str:
    """Add plural categories the locale needs, copying ``other``, when no branch shows ``#``.

    "{n, plural, one {Skipped files} other {Skipped files}}" in Polish needs few and many;
    when the number is not printed the forms do not vary by it, so ``other`` is right
    for them too. A branch with ``#`` needs real grammar: left to the gate (V03).
    """
    from .cldr import required_plural_categories

    try:
        needed = set(required_plural_categories(locale) or ())
    except Exception:  # noqa: BLE001 - unknown locale: nothing to fill
        return out
    if not needed:
        return out
    for m in list(_PLURAL_HEAD.finditer(out))[::-1]:
        parsed = _plural_branches(out, m.start())
        if not parsed:
            continue
        end, branches = parsed
        missing = needed - set(branches)
        if not missing or "other" not in branches:
            continue
        bodies = [out[a:b] for a, b in branches.values()]
        if any("#" in body for body in bodies):
            continue
        other = out[slice(*branches["other"])]
        close = end - 1
        extra = "".join(f" {cat} {{{other}}}" for cat in sorted(missing))
        out = out[:close].rstrip() + extra + out[close:]
    return out


def normalize_candidate(source: str, text: str, locale: str) -> tuple[str, list[str]]:
    """Clean model output against its source; return ``(text, steps_applied)``."""
    steps: list[str] = []
    out = (text or "").strip()
    if not out:
        return out, steps
    if "\n" not in source and "\n" in out:
        # A one-line source: the model added an explanation or alternatives below the
        # answer. Keep the first line; the gate still judges it (ADR-137).
        lines = out.splitlines()
        first = lines[0].strip()
        rest = [ln.strip() for ln in lines[1:]]
        # Only a trailing explanation is dropped: a blank line before it, or a line that
        # reads as a note. An answer broken across two lines is left to the gate.
        explained = bool(rest) and (rest[0] == "" or _EXPLANATION.match(rest[0]) is not None)
        if first and explained and first.count("{") == first.count("}"):
            out = first
            steps.append("first_line")
    stripped = _strip_wrapper(source, out)
    if stripped != out:
        out = stripped
        steps.append("quotes")
    unquoted = _strip_icu_branch_quotes(source, out)
    if unquoted != out:
        out = unquoted
        steps.append("icu_quotes")
    filled = _fill_plural_categories(out, locale)
    if filled != out:
        out = filled
        steps.append("plural_fill")
    lead = source.lstrip()[:1]
    if lead in _SYMBOL_WORDS and not out.startswith(lead):
        for word in _SYMBOL_WORDS[lead]:
            if out.casefold().startswith(word + " "):
                out = lead + out[len(word) + 1:].lstrip()
                steps.append("symbol")
                break
    if "…" in source and "..." not in source and "..." in out:
        out = out.replace("...", "…")
        steps.append("ellipsis")
    cased = _match_case(source, out, locale)
    if cased != out:
        out = cased
        steps.append("case")
    return out, steps
