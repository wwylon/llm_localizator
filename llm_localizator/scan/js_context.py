"""Context-aware string-literal pass for JS / TS / JSX (scanner bench, iteration 1).

The sink rules in ``raw_js`` and ``next_intl`` only see text in a few
syntactic places (JSX text, ``el()``, ``innerHTML``). Real UIs put most copy in
plain literals: ternaries, ``return`` values, ``+`` concatenations, label
arrays, ``label:`` object fields, helper arguments and template literals. This
pass reads every literal once, with its surroundings, and decides from context:

* never: object keys, comparisons, imports, selectors/storage/event names,
  ``t()``/``uiT()`` arguments (already routed), console output, TS unions;
* high: dialog/toast/error sinks and UI property names with prose;
* medium: prose anywhere else, capitalised labels in label positions;
* low: thrown errors and other weak signals.

One linear tokenizer (comments, regex literals and nested templates aware).

M3 split: the tokenizer is ``js_tokenizer``, the per-literal verdict ``js_judge`` and the own-line markup text pass
``markup_text``. This module drives them over a file and stays the import point for the other scanners.
"""

from __future__ import annotations

import re

from .base import ScanResult, line_number
from .js_judge import _CAP_LABEL, _add, _is_copy_shape, _llm_prompt_name, _Seen, judge, local_ui_sinks
from .js_tokenizer import _HOLE, JsLiteral, _unescape, iter_js_literals
from .markup_text import markup_text_pass, single_word_text
from .prose import grade, is_prose
from .usage_calls import ROUTED_CALLS, is_routed_callee  # noqa: F401  (ROUTED_CALLS re-exported, see test_locate_and_usage)

__all__ = [
    "context_pass", "scan_js_literals", "iter_js_literals", "JsLiteral", "markup_text_pass", "single_word_text",
]

_TAG = re.compile(r"<(/)?\s*([a-zA-Z][\w-]*)([^<>]*)>")
_HTML_ATTR = re.compile(
    r"""\b(title|placeholder|alt|aria-label|aria-description|label|data-tooltip|tooltip)\s*=\s*(["'])([^"'<>]*?)\2""",
    re.I,
)


_SKIP_TAGS = frozenset({"script", "style", "code", "pre", "kbd", "svg", "path", "textarea"})


def _html_pieces(raw: str) -> list[tuple[int, str, str]]:
    """(offset, text, kind) for text nodes and user attributes in an HTML fragment.

    Splits on tags in one pass (no lazy/overlapping regex), so a long email
    template stays linear.
    """
    out: list[tuple[int, str, str]] = []
    pos = 0
    tag_name, tag_attrs = "", ""
    for m in _TAG.finditer(raw):
        _add_piece(out, raw, pos, m.start(), tag_name, tag_attrs)
        if m.group(1):  # closing tag
            tag_name, tag_attrs = "", ""
        else:
            tag_name, tag_attrs = m.group(2).lower(), m.group(3)
        pos = m.end()
    _add_piece(out, raw, pos, len(raw), tag_name, tag_attrs)
    for m in _HTML_ATTR.finditer(raw):
        out.append((m.start(3), m.group(3), "attr"))
    return out


def _add_piece(out: list, raw: str, start: int, end: int, tag: str, attrs: str) -> None:
    if tag in _SKIP_TAGS or "data-i18n" in attrs:
        return
    chunk = raw[start:end]
    if "<" in chunk or ">" in chunk:
        return
    stripped = chunk.strip()
    if stripped:
        out.append((start + chunk.index(stripped[0]), stripped, "text"))


#: ``['Enter', 'Tab'].includes(x)`` / ``.indexOf(x)``: the array is a lookup set for code, not copy.
_MEMBERSHIP_ARRAY = re.compile(
    r"""\[\s*(?:'[^'
]*'|"[^"
]*")(?:\s*,\s*(?:'[^'
]*'|"[^"
]*"))*\s*,?\s*\]\s*\.(?:includes|indexOf|has)\s*\("""
)


def scan_js_literals(
    text: str, rel: str, result: ScanResult, *, line_offset: int = 0, skip: set | None = None,
) -> None:
    """Append context-judged literal hits for one JS/TS/JSX source (or script block)."""
    seen = skip if skip is not None else _Seen()
    sinks = local_ui_sinks(text)
    lits = iter_js_literals(text)
    joined_into: set[int] = set()  # literals already part of a reported sentence (v17)
    membership = [m.span() for m in _MEMBERSHIP_ARRAY.finditer(text)]
    for idx, lit in enumerate(lits):
        if idx in joined_into:
            continue
        if membership and any(a <= lit.start < b for a, b in membership):
            continue  # ``["Tab", "Space"].includes(e.key)``: a lookup table, not copy
        quoted_html = lit.quote != "tpl" and _QUOTED_HTML.search(lit.text) is not None
        if lit.in_template_html or quoted_html:
            if lit.routed_fallback or is_routed_callee(lit.callee):
                continue
            if lit.name and _llm_prompt_name(lit.name):
                continue  # LLM prompt template
            segments = lit.segments or [(lit.start + 1, len(lit.text))]
            for off, piece, kind in _html_pieces(lit.text):
                # A piece may still straddle ``${}``: each static fragment stands alone.
                for frag_off, frag in _fragments(off, piece):
                    t = " ".join(_unescape(frag).split())
                    if not t or not _is_copy_shape(t):
                        continue
                    if is_prose(t) or _CAP_LABEL.match(t):
                        conf = grade(t)
                    elif len(t) >= 2:
                        conf = "low"
                    else:
                        continue
                    line = line_number(text, _source_index(segments, frag_off)) + line_offset
                    where = "a template literal" if lit.quote == "tpl" else "a string"
                    _add(result, seen, t, rel, line, conf, f"HTML in {where} ({kind})")
            continue
        verdict = judge(lit, lit.text, sinks)
        if verdict is None:
            continue
        conf, reason = verdict
        line = line_number(text, lit.start) + line_offset
        shown = " ".join(lit.text.replace(_HOLE, " … ").split())
        if lit.next == "+" and lit.quote != "tpl-text":
            sentence, used = _concat_sentence(text, lits, idx)
            if used or sentence.endswith("{…}"):
                joined_into.update(used)
                shown = sentence
                reason += "; a sentence built with +: use one ICU message with placeholders"
        _add(result, seen, shown, rel, line, conf, reason)


#: Between two pieces of one sentence: ``+``, or ``+ <simple expression> +``.
_CONCAT_GAP = re.compile(r"\s*\+\s*(?:([\w$.\[\]()?:]+(?:\([^()\n]*\))?)\s*\+\s*)?")


def _concat_sentence(text: str, lits: list, idx: int) -> tuple[str, list[int]]:
    """``"Saved " + n + " files"`` -> ("Saved {…} files", [indices joined after idx]).

    Joins following string literals while the source between them is a ``+`` chain on
    one line; expression operands become ``{…}``. Stops at the first other token.
    """
    parts = [lits[idx].text]
    used: list[int] = []
    end = lits[idx].end
    j = idx + 1
    while j < len(lits):
        nxt = lits[j]
        if nxt.quote not in ("'", '"', "`") and nxt.quote != "tpl":
            break
        gap = text[end:nxt.start - 1]
        m = _CONCAT_GAP.fullmatch(gap)
        if not m or "\n" in gap:
            break
        if m.group(1):
            parts.append("{…}")
        parts.append(nxt.text.replace(_HOLE, "{…}"))
        used.append(j)
        end = nxt.end
        j += 1
    tail = text[end:end + 40]
    tm = re.match(r"\s*\+\s*([\w$.\[\]]+(?:\([^()\n]*\))?)", tail)
    if tm and not re.match(r"\s*\+\s*[\w$.\[\]]+(?:\([^()\n]*\))?\s*\+\s*['\"`]", tail):
        parts.append("{…}")  # trailing operand ("Total: " + n)
    if not used and len(parts) == 1:
        return parts[0], []
    return " ".join("".join(parts).split()), used


_QUOTED_HTML = re.compile(r"<(?:/?[a-zA-Z][\w-]*)[^<>]*>")


def _fragments(off: int, piece: str):
    """Static fragments of an HTML piece, split where ``${}`` stood."""
    pos = off
    for frag in piece.split(_HOLE):
        if frag.strip():
            yield pos + (len(frag) - len(frag.lstrip())), frag.strip()
        pos += len(frag) + 1


def _source_index(segments: list[tuple[int, int]], joined_off: int) -> int:
    """Map an offset in the rejoined template back to the source file."""
    base = 0
    for start, length in segments:
        if joined_off <= base + length:
            return start + (joined_off - base)
        base += length + 1
    return segments[-1][0]


_SCRIPT_BLOCK = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
_NON_JS_TYPE = re.compile(
    r"""type\s*=\s*["']?(?:application/(?:ld\+)?json|importmap|text/(?:template|html|x-template)|x-shader)""",
    re.I,
)


def context_pass(
    text: str, rel: str, result: ScanResult, *, is_html: bool = False, first_hit: int = 0,
) -> None:
    """Literal pass over a JS/TS file, or over each inline script of an HTML file.

    Text a sink rule already reported for this file (hits from *first_hit*
    on) is not repeated.
    """
    seen = _Seen(
        (h.line, " ".join(h.text.split()))
        for h in result.hardcoded[first_hit:] if h.file == rel
    )
    if not is_html:
        scan_js_literals(text, rel, result, skip=seen)
        return
    for m in _SCRIPT_BLOCK.finditer(text):
        attrs = m.group(1)
        if re.search(r"\bsrc\s*=", attrs) or _NON_JS_TYPE.search(attrs):
            continue
        offset = line_number(text, m.start(2)) - 1
        scan_js_literals(m.group(2), rel, result, line_offset=offset, skip=seen)
