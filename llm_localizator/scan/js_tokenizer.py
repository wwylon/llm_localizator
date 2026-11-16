"""One linear JavaScript tokenizer that yields every string literal with its surroundings (split from js_context, M3).

Comments, regex literals and nested template literals are understood. Each ``JsLiteral`` carries the token before and
after it, the callee and argument index it sits in, the property name it is assigned to, and whether it is the
fallback of an already-routed ``t("key") || "…"`` call. Judging what the literal means is ``js_judge``'s job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .usage_calls import routed_re

__all__ = ["JsLiteral", "iter_js_literals"]

_IDENT = re.compile(r"[\w$]")
#: Characters ``JsTokenizer._code`` reacts to: comments, regexes, quotes, brackets and commas (M4).
_CODE_STARTS = re.compile(r"""[/"'`()\[\]{},]""")
_CALLEE_BEFORE = re.compile(r"(?<![\w$])((?:new\s+)?[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)\s*$")
_NAME_BEFORE = re.compile(r"""(?:([A-Za-z_$][\w$-]*)|["'](@?[\w$-]+)["'])\s*$""")
_OPS = "=!<>&|?:+-*/%^~"
_REGEX_PREV_WORDS = {"return", "typeof", "case", "do", "else", "in", "of", "void", "yield", "await", "delete", "throw"}
_ROUTED_FALLBACK = routed_re("js_fallback")
# ``["act_col_x", "Label"]`` / ``("nav.home", "Home")``: catalogue key, then its fallback.
_KEY_PAIR = re.compile(r"""["'][a-z][a-z0-9]*(?:[_.][a-z0-9]+)+["']\s*,\s*$""")


@dataclass
class JsLiteral:
    start: int          # index of the opening quote / static-part start
    text: str           # unescaped content (template: one static part)
    quote: str          # ' " ` or "tpl" for a template static part
    prev: str
    next: str
    callee: str | None
    name: str | None    # property / attribute / assignment name
    in_template_html: bool = False
    routed_fallback: bool = False  # ``t('k') || 'Fallback'``
    #: HTML templates: (source index, length) of each static part, joined by _HOLE.
    segments: list[tuple[int, int]] | None = None
    end: int = 0  # index after the closing quote (plain strings only)
    arg: int = 0  # 0-based argument index inside the enclosing call


#: Stands in for a ``${…}`` expression when a template's parts are rejoined.
_HOLE = "\x00"
#: Static template text that is code, not copy: markup, CSS, paths, URLs, queries, headers.
_TPL_CODE = re.compile(
    r"[=;{}\\<>|#]|://|(?:^|\s)/|/\w|\w/|\w\("              # markup, paths, CSS/JS calls: rotate(, rgba(
    r"|\.(?:js|css|json|png|svg|html?|py|md|ya?ml|csv|log|txt|zip|pdf|xml)\b"
    r"|[a-z0-9][-_][a-z0-9]|--"                             # class lists, ids, CSS vars: btn-x, h-row-, --x
    r"|\b(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|Bearer|Basic|mailto|tel)\b")
#: ``variant: ${v}`` is a serialised field (YAML, CSS ``color:``), not a sentence.
_FIELD_PREFIX = re.compile(r"^\s*[a-z][\w-]*:\s*$")


def _template_text_copy(parts: list[str]) -> bool:
    """A non-HTML template whose static text reads as words around ``${…}``.

    ``made (${n} pts)`` and ``${days} days ago`` qualify; ``${base}/api/${id}``,
    ``${w}px``, ``btn-${kind}`` and ``SELECT * FROM ${t}`` do not.
    """
    static = " ".join(parts)
    if _TPL_CODE.search(static):
        return False
    if _FIELD_PREFIX.match(parts[0]) and not any(p.strip() for p in parts[1:]):
        return False
    # A part glued to an expression by - or _ builds an identifier: `tag-${v}`, `${id}-title`.
    if any(re.search(r"[A-Za-z0-9][-_]$", p) or re.match(r"^[-_][A-Za-z0-9]", p) for p in parts):
        return False
    if not re.search(r"[A-Za-z][a-z]{2,}", static):
        return False
    tokens = static.split()
    if len(tokens) == 1 and re.search(r"[-_.]", tokens[0]):
        return False  # one identifier-ish token joined to expressions: an id, a class
    return True


def _unescape(raw: str) -> str:
    return re.sub(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", _esc, raw, flags=re.S)


def _esc(m: re.Match) -> str:
    body = m.group(1)
    try:
        if body.startswith("u{"):
            return chr(int(body[2:-1], 16))
        if body[0] == "u" and len(body) == 5:
            return chr(int(body[1:], 16))
        if body[0] == "x" and len(body) == 3:
            return chr(int(body[1:], 16))
    except ValueError:
        return body
    return {"n": "\n", "t": "\t", "r": ""}.get(body, body)


def _prev_token(text: str, i: int) -> str:
    j = i - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return ""
    ch = text[j]
    if ch in _OPS:
        k = j
        while k - 1 >= 0 and text[k - 1] in _OPS and j - k < 2:
            k -= 1
        return text[k:j + 1]
    if _IDENT.match(ch):
        k = j
        while k - 1 >= 0 and _IDENT.match(text[k - 1]):
            k -= 1
        return text[k:j + 1]
    return ch


def _next_token(text: str, i: int) -> str:
    n = len(text)
    j = i
    while j < n and text[j] in " \t\r\n":
        j += 1
    if j >= n:
        return ""
    ch = text[j]
    if ch in _OPS:
        k = j
        while k + 1 < n and text[k + 1] in _OPS and k - j < 2:
            k += 1
        return text[j:k + 1]
    return ch


def _name_before(text: str, i: int) -> str | None:
    """Identifier before ``:`` / ``=`` that precedes position *i* (skipping the operator)."""
    j = i - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    if j < 0 or text[j] not in ":=":
        return None
    if text[j] == "=" and j > 0 and text[j - 1] in "=!<>":
        return None
    m = _NAME_BEFORE.search(text, max(0, j - 80), j)
    if not m:
        return None
    return m.group(1) or m.group(2)


class _Tokenizer:
    """Walks JS/TS, yielding literals with context. Linear in the file size."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)
        self.out: list[JsLiteral] = []
        self.calls: list[str | None] = []  # callee per open "(" / None for [ {
        self.args: list[int] = []  # top-level comma count per open bracket
        self.kinds: list[str] = []  # the opener of each entry: "(", "[", "{" or "${"

    def _push(self, kind: str, callee: str | None) -> None:
        self.kinds.append(kind)
        self.calls.append(callee)
        self.args.append(0)

    def _close(self, closer: str) -> None:
        """Pop the bracket *closer* closes. A stray closer pops nothing (M2: any closer popped the top entry, so one
        unbalanced ``)`` shifted every later literal's callee, even out of an enclosing ``${…}``)."""
        opener = {")": "(", "]": "[", "}": "{"}[closer]
        for depth in range(1, min(len(self.kinds), 8) + 1):
            kind = self.kinds[-depth]
            if kind == "${":
                return
            if kind == opener:
                del self.kinds[-depth:], self.calls[-depth:], self.args[-depth:]
                return

    def run(self) -> list[JsLiteral]:
        self._code(0, None)
        return self.out

    def _callee(self) -> str | None:
        return self.calls[-1] if self.calls else None

    def _code(self, i: int, stop: str | None) -> int:
        text, n = self.text, self.n
        depth = 0
        while i < n:
            ch = text[i]
            if ch == "/" and i + 1 < n and text[i + 1] == "/":
                nl = text.find("\n", i)
                i = n if nl < 0 else nl
                continue
            if ch == "/" and i + 1 < n and text[i + 1] == "*":
                close = text.find("*/", i + 2)
                i = n if close < 0 else close + 2
                continue
            if ch == "/" and self._regex_ok(i):
                i = self._skip_regex(i)
                continue
            if ch in "\"'":
                if i > 0 and (text[i - 1].isalnum() or text[i - 1] in "’"):
                    i += 1  # apostrophe in JSX text ("Don't"), not a string
                    continue
                i = self._string(i, ch)
                continue
            if ch == "`":
                i = self._template(i)
                continue
            if ch == "(":
                m = _CALLEE_BEFORE.search(text, max(0, i - 120), i)
                name = re.sub(r"\s+", "", m.group(1)) if m else None
                if name and name.startswith("new"):
                    name = name[3:]
                self._push("(", name)
            elif ch in "[{":
                if ch == "{":
                    depth += 1
                self._push(ch, None)
            elif ch == ",":
                if self.args:
                    self.args[-1] += 1
            elif ch in ")]}":
                if ch == "}":
                    if stop == "}" and depth == 0:
                        return i + 1
                    depth -= 1
                self._close(ch)
            # M4: every other character only advanced by one; jump to the next one a branch above reacts to.
            m = _CODE_STARTS.search(text, i + 1)
            i = m.start() if m else n
        return n

    def _regex_ok(self, i: int) -> bool:
        prev = _prev_token(self.text, i)
        if not prev:
            return True
        if prev in _REGEX_PREV_WORDS:
            return True
        return prev[-1] in "(,=:[!&|?{};+-*%<>~^"

    def _skip_regex(self, i: int) -> int:
        text, n = self.text, self.n
        j = i + 1
        in_class = False
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "\n":
                return i + 1  # not a regex after all
            if in_class:
                if ch == "]":
                    in_class = False
            elif ch == "[":
                in_class = True
            elif ch == "/":
                return j + 1
            j += 1
        return i + 1

    def _context(self, start: int, end: int) -> tuple[str, str, str | None, str | None]:
        return (
            _prev_token(self.text, start), _next_token(self.text, end),
            self._callee(), _name_before(self.text, start),
        )

    def _string(self, i: int, quote: str) -> int:
        text, n = self.text, self.n
        j = i + 1
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == quote:
                prev, nxt, callee, name = self._context(i, j + 1)
                lit = JsLiteral(i, _unescape(text[i + 1:j]), quote, prev, nxt, callee, name)
                lit.arg = self.args[-1] if self.args else 0
                window = max(0, i - 160)
                lit.routed_fallback = bool(
                    _ROUTED_FALLBACK.search(text, window, i) or _KEY_PAIR.search(text, window, i)
                )
                # ``{"Source text": "Tłumaczenie"}``: a value keyed by a prose
                # string is a translation table entry, not a leftover.
                last = self.out[-1] if self.out else None
                if (
                    last is not None and last.quote in "\"'" and " " in last.text.strip()
                    and last.prev in ("{", ",")  # an object key, not a ternary branch
                    and re.fullmatch(r"\s*:\s*", text[last.end:i] if last.end else "x")
                ):
                    lit.routed_fallback = True
                lit.end = j + 1
                self.out.append(lit)
                return j + 1
            if ch == "\n":
                return i + 1  # unterminated: treat the quote as a plain character
            j += 1
        return i + 1

    def _template(self, i: int) -> int:
        text, n = self.text, self.n
        prev, _, callee, name = _prev_token(text, i), "", self._callee(), _name_before(text, i)
        parts: list[tuple[int, str]] = []
        j = i + 1
        seg = j
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "`":
                parts.append((seg, text[seg:j]))
                nxt = _next_token(text, j + 1)
                html = any("<" in p and ">" in p for _, p in parts) or (
                    len(parts) > 1 and any(re.search(r"<\w|</", p) for _, p in parts)
                )
                window = max(0, i - 160)
                fallback = bool(
                    _ROUTED_FALLBACK.search(text, window, i) or _KEY_PAIR.search(text, window, i)
                )
                if html:
                    # One literal for the whole template: tags may span ``${}``.
                    lit = JsLiteral(
                        parts[0][0], _HOLE.join(raw for _, raw in parts), "tpl", prev, nxt,
                        callee, name, in_template_html=True, routed_fallback=fallback,
                    )
                    lit.segments = [(pos, len(raw)) for pos, raw in parts]
                    self.out.append(lit)
                    return j + 1
                if len(parts) > 1 and _template_text_copy([raw for _, raw in parts]):
                    # "made (${n} pts)": judge the sentence, not its "made (" / " pts)" halves.
                    lit = JsLiteral(
                        parts[0][0], _HOLE.join(_unescape(raw) for _, raw in parts), "tpl-text",
                        prev, nxt, callee, name, routed_fallback=fallback,
                    )
                    lit.segments = [(pos, len(raw)) for pos, raw in parts]
                    self.out.append(lit)
                    return j + 1
                for pos, raw in parts:
                    self.out.append(JsLiteral(
                        pos, _unescape(raw), "tpl", prev, nxt, callee, name,
                        routed_fallback=fallback,
                    ))
                return j + 1
            if ch == "$" and j + 1 < n and text[j + 1] == "{":
                parts.append((seg, text[seg:j]))
                self._push("${", "${")
                mark = len(self.kinds)
                j = self._code(j + 2, "}")
                # Drop whatever the expression left open, then the ``${`` marker itself.
                del self.kinds[mark - 1:], self.calls[mark - 1:], self.args[mark - 1:]
                seg = j
                continue
            j += 1
        return n


def iter_js_literals(text: str) -> list[JsLiteral]:
    return _Tokenizer(text).run()
