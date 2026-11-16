"""Text between tags on its own line, and single-word labels in markup (split from js_context, M3).

``markup_text_pass`` reads lines that sit between an opening and a closing tag (JSX, HTML, templates) and reports
the copy on them; ``single_word_text`` decides whether one short word inside an element is a label a person reads.
"""

from __future__ import annotations

import re

from .base import ScanResult, line_number
from .js_judge import _CAP_LABEL, _add, _is_copy_shape, _Seen
from .negatives import is_non_ui_literal
from .prose import LabelWordMatcher, grade, is_lone_word, is_short_label
from .usage_calls import ROUTED_LINE

__all__ = ["markup_text_pass", "single_word_text"]

_OWN_LINE_CODE = re.compile(r"[<>{}=;`]|=>|^\W*['\"]|[,]$|^(?:return|const|let|var|import|export|if|else|case|default|function|type|interface)\b")
#: A wrapped sentence may hold "; " ("stack hidden; picker limited to …."): v18.
_WRAPPED_PROSE = re.compile(r"^[A-Z][^;]*\w; [a-z][^;]*[.!?]$")
_SINGLE_WORD = LabelWordMatcher(2, 25)
_ROUTED_LINE = ROUTED_LINE
_BLOCK = re.compile(r"<(script|style|pre|code|svg)\b[^>]*>.*?</\1\s*>", re.S | re.I)


def markup_text_pass(
    text: str, rel: str, result: ScanResult, *, first_hit: int = 0, html: bool = False,
) -> None:
    """JSX/HTML text that sits alone on its own line (Prettier-wrapped markup).

    ``<button>\n  Start session\n</button>``: the per-line ``>text<`` rules
    never see it. A line counts when it has no code characters and a markup
    neighbour (the line above ends a tag, or the line below closes one).
    """
    seen = _Seen(
        (h.line, " ".join(h.text.split()))
        for h in result.hardcoded[first_hit:] if h.file == rel
    )
    blocked: list[tuple[int, int]] = []
    if html:
        blocked = [
            (line_number(text, m.start()), line_number(text, m.end())) for m in _BLOCK.finditer(text)
        ]
    lines = text.split("\n")
    nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
    for pos, i in enumerate(nonempty):
        s = lines[i].strip()
        lineno = i + 1
        if s.startswith(("//", "*", "/*", "#")) or _ROUTED_LINE.search(s):
            continue
        code = _OWN_LINE_CODE.search(s)
        if code and not (code.group() == ";" and _WRAPPED_PROSE.match(s)
                         and not _OWN_LINE_CODE.search(s.replace(";", ","))):
            continue
        if any(a <= lineno <= b for a, b in blocked):
            continue
        prev = lines[nonempty[pos - 1]].rstrip() if pos > 0 else ""
        nxt = lines[nonempty[pos + 1]].lstrip() if pos + 1 < len(nonempty) else ""
        opens = prev.endswith(">") and not prev.endswith(("=>", "->")) and not prev.rstrip().endswith("/>")
        closes = nxt.startswith("</")
        if not (opens or closes) or _ROUTED_LINE.search(prev):
            continue
        if not _is_copy_shape(s.replace("; ", ", ") if code else s):
            continue
        conf = grade(s, "none", label=(_CAP_LABEL.match,))
        if conf is None:
            continue
        _add(result, seen, " ".join(s.split()), rel, lineno, conf, "markup text on its own line")


#: Tags whose one-word text is a label. ``<div>Bridge</div>`` stays silent (brand risk).
_LABEL_TAGS = frozenset({
    "th", "td", "dt", "dd", "button", "a", "label", "legend", "summary", "option",
    "span", "strong", "b", "em", "small", "li", "caption", "figcaption", "title",
    "h1", "h2", "h3", "h4", "h5", "h6", "p",
})
#: Visually hidden text still goes to screen readers: ``class="sr-only"``, ``visually-hidden``.
_SR_ONLY = re.compile(r"""class\s*=\s*["'][^"']*\b(?:sr-only|visually-hidden|screen-reader-text)\b""")
_CLOSING_TAG = re.compile(r"\s*</([A-Za-z][\w.-]*)")
_LAST_TAG = re.compile(r"<\s*([A-Za-z][\w.-]*)([^<>]*)>\s*$")
#: A ``div`` whose class names a label is a label: ``<div class="g-name">Whist</div>``.
_LABEL_CLASS = re.compile(
    r"""class(?:Name)?\s*=\s*["'][^"']*?(?:name|title|label|heading|header|head|caption|eyebrow"""
    r"""|kicker|tab|chip|badge|legend|hint|subtitle)\b""", re.I)
#: A presentational ``div`` (inline font styling) holding one word is a label too.
_STYLED_TEXT = re.compile(r"""style\s*=\s*["'][^"']*font-(?:size|weight)""", re.I)
#: Several one-word ``<div>`` cells on one line form a header row.
_DIV_CELL = re.compile(r"<div>\s*[A-Z][A-Za-z]{1,24}\s*</div>")
#: Lowercase headings are copy in these tags (``<th>board</th>``); identifiers are not.
_LOWER_LABEL_TAGS = frozenset({"th", "dt", "label", "legend", "caption", "button", "summary"})  # not option: ids
#: Elements whose text is always read by a person (not ``code``, ``option``, ``pre`` or a bare ``div``).
_TEXT_TAGS = frozenset({
    "p", "li", "th", "a", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "b", "i", "small",
    "figcaption", "dt", "button", "label", "legend", "caption", "summary", "title",  # not td/dd/span: cells and values are data
})
_LOWER_WORD = re.compile(r"^[a-z]{3,24}$")
_SNAKE_LABEL = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+){1,4}$")
_LOWER_PHRASE = re.compile(r"^[a-z]{2,}(?: [(]?[a-z]+[),]?){1,7}$")


def single_word_text(text: str, line: str = "", start: int = 0) -> bool:
    """A one-word text node that is a label.

    Capitalised in a label tag (``<th>Status</th>``), in a ``div`` whose class or
    inline style marks a label, or in a row of one-word ``div`` cells; lowercase only
    in heading-like tags (``<th>board</th>``; ``<option>`` lowercase text is usually an id). A bare
    ``<div>Bridge</div>`` stays silent (brand risk).
    """
    if is_non_ui_literal(text):
        return False
    m = _LAST_TAG.search(line[:start]) if line else None
    if m and _SR_ONLY.search(m.group(2)):
        return True  # <span class="sr-only">(current)</span>: read aloud, still copy
    if not m and line:
        # ``<span>&larr;</span> Previous</a>``: the text follows an inline element; its owner closes after it.
        at = line.find(text, start)
        after = _CLOSING_TAG.match(line[at + len(text):]) if at >= 0 else None
        if after:
            tag = after.group(1).lower()
            return bool(_SINGLE_WORD.match(text)) and tag in _LABEL_TAGS
    if not m:
        return False
    tag, attrs = m.group(1).lower(), m.group(2)
    if _SINGLE_WORD.match(text):
        if tag in _LABEL_TAGS:
            return True
        if tag == "div":
            return bool(_LABEL_CLASS.search(attrs) or _STYLED_TEXT.search(attrs)
                        or len(_DIV_CELL.findall(line)) >= 3)
        return False
    # Not th: column headers named after data fields (<th>hand_id</th>) are ids.
    labelish = tag in ("label", "dt", "legend") or (
        tag in ("span", "div") and bool(_LABEL_CLASS.search(attrs)))
    if labelish and _SNAKE_LABEL.match(text):
        return True  # <span class="label">master_seed</span>: a knob name shown as a label (v18)
    if tag in _LOWER_LABEL_TAGS and _LOWER_PHRASE.match(text):
        return True  # <label>raise to (total, this street)</label> (v18)
    if tag in _TEXT_TAGS and (is_lone_word(text) or is_short_label(text)):
        return True  # <p>nepálsky</p>: visible text in a text element, even in a language that writes names in lower case
    return tag in _LOWER_LABEL_TAGS and bool(_LOWER_WORD.match(text))
