"""Raw JS/HTML scanner for projects using vanilla i18n.t() / data-i18n patterns.

Covers:
  * ``i18n.t('key')`` and ``i18n.t("key")`` call sites in .js files
  * ``data-i18n="key"`` / ``data-i18n-placeholder="key"`` / ``data-i18n-attr="key"``
    attributes in .html and .js template literals
  * Hardcoded user-visible strings in HTML (text nodes, title/placeholder attrs)
  * Hardcoded user-visible strings in JS template literals assigned to innerHTML
  * UI helper sinks (``card(title, hint)``) and quoted ``innerHTML`` / ``outerHTML``

The detector is conservative — false positives waste developer time, so
single-word strings, API paths, CSS identifiers, and short tokens are skipped.
"""

from __future__ import annotations

from .base import relative_posix

import re
import threading
from pathlib import Path

from ..core.languages import language
from .base import (
    HardcodedString, Scanner, ScanResult, Usage, line_number, paths_with_suffixes,
)
from .negatives import (
    is_listener_event_arg,
    is_non_ui_literal,
    is_non_user_attr_value,
)
from .js_context import context_pass, markup_text_pass, single_word_text
from .prose import LabelWordMatcher, grade, is_prose
from .usage_calls import routed_re
from .sfc import blank_markup_comments

__all__ = ["RawJsScanner", "UI_HELPER_SINKS"]

# ---------- usage patterns ----------

_I18N_T = re.compile(
    r"""\bi18n(?:\.t|\[\s*["']t["']\s*\])\(\s*["'`]([\w.]+)["'`]\s*[,)]"""
)
_DATA_I18N = re.compile(r"""data-i18n(?:-placeholder|-attr)?\s*=\s*["']([\w.]+)["']""")

# ---------- hardcoded string patterns ----------

_HTML_TEXT = re.compile(r">\s*([^<>{}\n]{1,}?)\s*<")  # one ideograph is a whole label ("删")
_HTML_LEADING = re.compile(r"^([^<>{}\n]{2,}?)\s*</[a-zA-Z]")
#: One capitalised word: ``aria-label="Close"``, ``title="Delete"``.
_CAP_WORD = LabelWordMatcher(3, 24)
_USER_ATTR_PLAIN = re.compile(
    r"""\b(title|placeholder|alt|aria-label)\s*=\s*["']([^"'{}\n]{3,})["']"""
)
_INNER_HTML = re.compile(r"""(?:innerHTML|textContent|outerHTML)\s*=\s*`([^`]{4,})`""")
_INNER_HTML_QUOTED = re.compile(
    r"""(?:innerHTML|outerHTML)\s*=\s*(["'])((?:\\.|(?!\1)[^\\])*)\1""",
)
# L29: the body excludes only its own quote, so ``"Don't save"`` matches (both quote kinds were excluded).
_TEXT_ASSIGN = re.compile(
    r"""(?:\.textContent|\.innerText)\s*=\s*(["'])((?:\\.|(?!\1)[^\\\n]){2,})\1"""
)
_WIDGET_TAGS = (
    "button|a|label|span|p|strong|em|small|summary|option|th|td|"
    "h[1-6]|legend|figcaption|li|dt|dd|div|section"
)
# Third arg must be a complete string literal (ends before ``)`` or ``,``),
# so ``el("div", "", "No " + level)`` is not reported as the truncated ``"No "``.
_EL_CALL = re.compile(
    rf"""\bel\s*\(\s*["']({_WIDGET_TAGS})["']\s*,\s*["'][^"']*["']\s*,\s*["']([^"']{{2,}})["']\s*[),]"""
)
# Concatenated third arg: leading string still user-facing copy.
_EL_CALL_CONCAT = re.compile(
    rf"""\bel\s*\(\s*["']({_WIDGET_TAGS})["']\s*,\s*["'][^"']*["']\s*,\s*["']([^"']{{2,}})["']\s*\+"""
)
_CREATE_TEXT = re.compile(
    r"""\bcreateTextNode\s*\(\s*(["'])((?:\\.|(?!\1)[^\\\n]){2,})\1"""
)
_DIALOG = re.compile(
    r"""\b(?:window\.)?(?:confirm|alert|prompt)\s*\(\s*(["'])((?:\\.|(?!\1)[^\\\n]){2,})\1"""
)
# Helper name → 0-based arg indexes that are user-facing copy.
UI_HELPER_SINKS: dict[str, tuple[int, ...]] = {
    "card": (0, 1),
    "field": (0, 2),   # label, hint (control is arg 1)
    "panel": (0, 1),   # title/label, optional note string
    "section": (0,),   # titleText
    "setStatus": (0,),
    "showError": (0,),
    "say": (0,),
    "action": (0,),  # editor toolbar button label
}
_HELPER_NAME = re.compile(
    r"""(?<![.\w])(""" + "|".join(re.escape(n) for n in sorted(UI_HELPER_SINKS)) + r""")\s*\(""",
)
_EL_NAME = re.compile(r"""(?<![.\w])el\s*\(""")
# Flat or nested string arrays passed to forEach/map — table headers, export labels.
_LABEL_ARRAY = re.compile(
    r"""(\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])\s*\.\s*(?:forEach|map)\s*\(""",
    re.DOTALL,
)
# Dogfood / package keys are snake_case with an underscore (act_col_…, dash_…).
# Bare ids like "user" / "locale" are API values paired with visible labels.
_CATALOGUE_KEY = re.compile(r"^[a-z][a-z0-9]*_[a-z0-9_]{1,64}$")
_STR_ARG = re.compile(r"""(["'])((?:\\.|(?!\1)[^\\])*)\1""")


#: A call longer than this is unbalanced source, not one helper call.
_MAX_CALL_SPAN = 4_000


def _balanced_call_inner(
    text: str, open_paren: int, limit: int = _MAX_CALL_SPAN,
) -> tuple[str, int] | None:
    """Return (inner, end_index) for the call starting at *open_paren* ``(``.

    Strings (template literals too) and comments do not move the depth. Gives
    up after *limit* characters so one unclosed call cannot make a whole-file
    pass quadratic.
    """
    close = _paren_pairs(text).get(open_paren)
    if close is None or close - open_paren > limit:
        return None
    return text[open_paren + 1 : close], close + 1


_CALL_TOKEN = re.compile(r"""["'`()]|//|/\*""")
# Rest of a string after its opening quote. Plain quotes stop at a newline
# (an apostrophe in prose must not swallow the file); templates may span lines.
_STRING_END = {
    '"': re.compile(r'(?:[^"\\\n]|\\.)*"'),
    "'": re.compile(r"(?:[^'\\\n]|\\.)*'"),
    "`": re.compile(r"(?:[^`\\]|\\.)*`", re.DOTALL),
}
_PAIRS_MEMO = threading.local()


def _paren_pairs(text: str) -> dict[int, int]:
    """``(`` index → matching ``)`` index for the whole file, in one linear pass.

    Parens inside strings and comments are ignored. Memoised on the text, so
    every helper call in a file shares one pass.
    """
    memo = getattr(_PAIRS_MEMO, "value", None)
    if memo is not None and memo[0] is text:
        return memo[1]
    pairs: dict[int, int] = {}
    stack: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        m = _CALL_TOKEN.search(text, i)
        if m is None:
            break
        tok = m.group()
        i = m.end()
        if tok in _STRING_END:
            end = _STRING_END[tok].match(text, i)
            if end is not None:
                i = end.end()
        elif tok == "//":
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
        elif tok == "/*":
            close = text.find("*/", i)
            i = n if close < 0 else close + 2
        elif tok == "(":
            stack.append(m.start())
        elif stack:
            pairs[stack.pop()] = m.start()
    _PAIRS_MEMO.value = (text, pairs)
    return pairs
_CLASS_LIST = re.compile(r"^[a-z][\w-]*(?:\s+[a-z][\w-]*)+$")
_WIDGET_WORD = re.compile(r"^[A-Z][A-Za-z]{1,24}$")
_TL_PROSE = re.compile(
    r"`<(?:td|th|button|h[1-6]|span|label|p|a|li|option)[^`]{0,80}>\s*([^<]{2,}?)\s*</"
)
_TEMPLATE_EXPR = re.compile(r"\$\{[^}]*\}")


def _strip_template_exprs(s: str) -> str:
    return _TEMPLATE_EXPR.sub("…", s)


def _is_prose(text: str) -> bool:
    return is_prose(text)


def _is_ui_copy(text: str, *, widget: bool = False) -> bool:
    """Prose, or a capitalised single word when the site is a known UI widget."""
    text = text.strip()
    if not text or is_non_ui_literal(text):
        return False
    if _CLASS_LIST.fullmatch(text):
        return False
    if _is_prose(text):
        return True
    if widget and _WIDGET_WORD.fullmatch(text):
        return True
    return False


def _helper_string_args(call_inner: str) -> list[tuple[int, str]]:
    """Return (arg_index, text) for each top-level string literal in a call."""
    out: list[tuple[int, str]] = []
    depth = 0
    i = 0
    arg_i = 0
    n = len(call_inner)
    while i < n:
        ch = call_inner[i]
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and ch == ",":
            arg_i += 1
            i += 1
            continue
        if depth == 0 and ch in "\"'":
            m = _STR_ARG.match(call_inner, i)
            if m:
                out.append((arg_i, m.group(2)))
                i = m.end()
                continue
        i += 1
    return out


def _line_at(text: str, index: int) -> int:
    return line_number(text, index)


_WIDGET_TAG_SET = frozenset(
    t for t in _WIDGET_TAGS.split("|") if t != "h[1-6]"
) | frozenset(f"h{i}" for i in range(1, 7))


def _el_third_is_concat(call_inner: str) -> bool:
    """True when the third top-level arg is an expression with ``+`` (concat)."""
    depth = 0
    arg_i = 0
    i = 0
    n = len(call_inner)
    third_start = None
    while i < n:
        ch = call_inner[i]
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and ch == ",":
            if arg_i == 2:
                break
            arg_i += 1
            if arg_i == 2:
                third_start = i + 1
            i += 1
            continue
        if depth == 0 and ch in "\"'":
            m = _STR_ARG.match(call_inner, i)
            if m:
                i = m.end()
                continue
        i += 1
    if third_start is None:
        return False   # fewer than three arguments
    # L30: only the third argument (the loop stops on the comma after it), and a ``+`` inside a string is text.
    third = call_inner[third_start:i]
    return "+" in re.sub(r""""(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'""", "", third)


def _label_array_texts(array_src: str) -> list[str]:
    """Extract user-facing labels from a ``[…]`` before ``.forEach``/``.map``.

    Flat ``["A", "B"]`` → both. Nested ``[["key", "Label"]]`` → Label only when
    *key* does not look like a catalogue id (those are uiT fallbacks).
    Nested ``[["user", "By translator"]]`` → second element (API id + label).
    """
    inner = array_src.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    out: list[str] = []
    depth = 0
    i = 0
    n = len(inner)
    elem_start = 0
    elements: list[str] = []
    while i < n:
        ch = inner[i]
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and ch == ",":
            elements.append(inner[elem_start:i].strip())
            elem_start = i + 1
            i += 1
            continue
        if depth == 0 and ch in "\"'":
            m = _STR_ARG.match(inner, i)
            if m:
                i = m.end()
                continue
        i += 1
    tail = inner[elem_start:].strip()
    if tail:
        elements.append(tail)

    for elem in elements:
        if not elem:
            continue
        if elem.startswith("[") and elem.endswith("]"):
            strs = [s.strip() for _i, s in _helper_string_args(elem[1:-1])]
            if len(strs) >= 2:
                key, label = strs[0], strs[1]
                if _CATALOGUE_KEY.fullmatch(key):
                    continue  # uiT(key, fallback) catalogue pair
                out.append(label)
            elif len(strs) == 1:
                out.append(strs[0])
            continue
        m = _STR_ARG.match(elem)
        if m:
            out.append(m.group(2).strip())
    return out


def _emit_html_fragment_prose(
    html: str, rel: str, lineno: int, result: ScanResult, *, reason: str,
    confidence: str = "medium",
) -> None:
    pieces: list[str] = []
    for m in _HTML_TEXT.finditer(html):
        pieces.append(m.group(1).strip())
    lead = _HTML_LEADING.match(html.strip())
    if lead:
        pieces.append(lead.group(1).strip())
    seen: set[str] = set()
    for text in pieces:
        if not text or text in seen or is_non_ui_literal(text):
            continue
        seen.add(text)
        if not _is_ui_copy(text, widget=True):
            continue
        conf = confidence
        if confidence != "medium" and _is_prose(text):
            conf = "high"
        result.hardcoded.append(HardcodedString(
            text, rel, lineno, reason, confidence=conf,
        ))
    for attr, value in _USER_ATTR_PLAIN.findall(html):
        value = value.strip()
        if _is_prose(value):
            result.hardcoded.append(HardcodedString(
                value, rel, lineno, reason, confidence="high",
            ))


_ALREADY_I18N = routed_re("raw_js_line")
_IGNORE_TAGS = ("<script", "<style", "//", " * ", "/*", "*/")


class RawJsScanner(Scanner):
    """Scans raw JS and HTML files for i18n.t() usage and hardcoded strings."""

    @property
    def routing_note(self) -> str:
        return "Replace the literal with i18n.t() or a data-i18n attribute."

    @property
    def file_glob(self) -> str:
        return "**/*.[jh][st][ms]*"  # .js, .html, .htm, .ts (matches broadly; filtered below)

    def iter_files(self):
        """Override to target only .js and .html files."""
        suffixes = language("javascript").extensions + language("html").extensions
        # Skip i18n.js itself; test files are handled by path_is_skipped.
        yield from paths_with_suffixes(self, suffixes, skip_names=("i18n.js",))

    def scan_file(self, path: Path, lines: list[str], result: ScanResult) -> None:
        rel = relative_posix(path, self.root)
        if path.suffix.lower() in (".html", ".htm"):   # L31: ``.HTML`` is markup too
            # ``Welcome back, {{ name }}!``: Jinja, Django, Handlebars, Angular and Vue all put expressions in text.
            # Blank the engine code and keep a slot, so the static words around it are still seen.
            from .views import scan_markup_view
            from .templates import template_markup

            scan_markup_view(self, rel, template_markup("\n".join(lines), "jinja"), result)
            return
        self.scan_text(rel, lines, False, result)

    def scan_text(self, rel: str, lines: list[str], is_html: bool, result: ScanResult) -> None:
        """Scan already-split lines as markup (``is_html``) or as script."""
        if is_html:
            lines = blank_markup_comments("\n".join(lines)).split("\n")
        text = "\n".join(lines)
        before = len(result.hardcoded)

        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                continue

            for key in _I18N_T.findall(line):
                ns, bare = _split_key(key)
                result.usages.append(Usage(ns, bare, rel, lineno))

            for key in _DATA_I18N.findall(line):
                ns, bare = _split_key(key)
                result.usages.append(Usage(ns, bare, rel, lineno))

            if _ALREADY_I18N.search(line):
                continue
            if any(stripped.lower().startswith(t) for t in _IGNORE_TAGS):   # ``<SCRIPT`` too (L31)
                continue

            if is_html:
                self._check_html_line(line, rel, lineno, result)
            else:
                self._check_js_line(line, rel, lineno, result)

        if not is_html:
            self._check_js_helpers(text, rel, result)
            self._check_js_el_calls(text, rel, result)
            self._check_js_label_arrays(text, rel, result)
        context_pass(text, rel, result, is_html=is_html, first_hit=before)
        if is_html:
            markup_text_pass(text, rel, result, first_hit=before, html=True)

    @staticmethod
    def _in_comment(text: str, index: int) -> bool:
        line_start = text.rfind("\n", 0, index) + 1
        prefix = text[line_start:index].lstrip()
        return prefix.startswith("//") or prefix.startswith("*") or prefix.startswith("/*")

    @staticmethod
    def _check_js_helpers(text: str, rel: str, result: ScanResult) -> None:
        """Whole-file pass so multiline card(...) sinks are visible."""
        for helper_m in _HELPER_NAME.finditer(text):
            if RawJsScanner._in_comment(text, helper_m.start()):
                continue
            name = helper_m.group(1)
            open_paren = helper_m.end() - 1
            parsed = _balanced_call_inner(text, open_paren)
            if parsed is None:
                continue
            inner, _end = parsed
            if not any(ch in inner for ch in "\"'"):
                continue
            positions = UI_HELPER_SINKS.get(name, ())
            lineno = _line_at(text, helper_m.start())
            for arg_i, arg_text in _helper_string_args(inner):
                if arg_i not in positions:
                    continue
                arg_text = arg_text.strip()
                if not _is_ui_copy(arg_text, widget=True):
                    continue
                conf = grade(arg_text)
                result.hardcoded.append(HardcodedString(
                    arg_text, rel, lineno,
                    f"{name}(…) user-facing arg — route through uiT/data-i18n",
                    confidence=conf,
                ))

    @staticmethod
    def _check_js_el_calls(text: str, rel: str, result: ScanResult) -> None:
        """Whole-file ``el(...)`` so multiline third-arg labels are visible."""
        for el_m in _EL_NAME.finditer(text):
            if RawJsScanner._in_comment(text, el_m.start()):
                continue
            open_paren = el_m.end() - 1
            parsed = _balanced_call_inner(text, open_paren)
            if parsed is None:
                continue
            inner, _end = parsed
            args = _helper_string_args(inner)
            if len(args) < 3:
                continue
            tag = args[0][1].strip()
            if tag not in _WIDGET_TAG_SET:
                continue
            # Skip if this call site already routes through uiT / i18n.t.
            if re.search(r"\buiT\s*\(", inner) or re.search(r"\bi18n\.t\s*\(", inner):
                continue
            label = args[2][1].strip()
            concat = _el_third_is_concat(inner)
            if concat and not _is_prose(label):
                continue
            if concat and len(label.split()) < 2 and not label.endswith((".", "!", "?", ":")):
                # Short leading fragment of a concatenation — not actionable alone.
                continue
            if not _is_ui_copy(label, widget=True):
                continue
            conf = grade(label)
            result.hardcoded.append(HardcodedString(
                label, rel, _line_at(text, el_m.start()),
                f'el("{tag}", …) user-facing label — route through uiT/data-i18n',
                confidence=conf,
            ))

    @staticmethod
    def _check_js_label_arrays(text: str, rel: str, result: ScanResult) -> None:
        """``["Translator", "Changes"].forEach`` / tuple export label lists."""
        for m in _LABEL_ARRAY.finditer(text):
            if RawJsScanner._in_comment(text, m.start()):
                continue
            # Body often has uiT(row[0], row[1]) — those are catalogue fallbacks.
            body_start = m.end() - 1
            body = _balanced_call_inner(text, body_start, limit=20_000)
            body_inner = body[0] if body else ""
            if re.search(r"\buiT\s*\(", body_inner) or re.search(r"\bi18n\.t\s*\(", body_inner):
                continue
            array_src = m.group(1)
            lineno = _line_at(text, m.start())
            for label in _label_array_texts(array_src):
                if not _is_ui_copy(label, widget=True):
                    continue
                conf = grade(label)
                result.hardcoded.append(HardcodedString(
                    label, rel, lineno,
                    "label array .forEach/.map — route through uiT/data-i18n",
                    confidence=conf,
                ))

    @staticmethod
    def _check_html_line(line: str, rel: str, lineno: int, result: ScanResult) -> None:
        for m in _HTML_TEXT.finditer(line):
            text = m.group(1).strip()
            if is_non_ui_literal(text) or is_non_user_attr_value(line, text):
                continue
            if _is_prose(text):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno, confidence="high",
                ))
            elif single_word_text(text, line, m.start(1)):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno, "single-word HTML text", confidence="medium",
                ))

        for attr, value in _USER_ATTR_PLAIN.findall(line):
            value = value.strip()
            if is_non_ui_literal(value) and not (_CAP_WORD.match(value) and attr != "alt"):
                continue
            if _is_prose(value):
                result.hardcoded.append(HardcodedString(
                    value, rel, lineno,
                    f"{attr}= attribute not routed through data-i18n or i18n.t()",
                    confidence="high",
                ))
            elif _CAP_WORD.match(value) and attr != "alt":
                result.hardcoded.append(HardcodedString(
                    value, rel, lineno,
                    f"{attr}= one-word label not routed through data-i18n or i18n.t()",
                    confidence="medium",
                ))

    @staticmethod
    def _check_js_line(line: str, rel: str, lineno: int, result: ScanResult) -> None:
        cleaned = _strip_template_exprs(line)
        for m in _TL_PROSE.finditer(cleaned):
            text = m.group(1).strip()
            if is_listener_event_arg(line, text) or is_non_ui_literal(text):
                continue
            if _is_prose(text):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno, confidence="medium",
                ))

        for text in _INNER_HTML.findall(cleaned):
            text = text.strip()
            if is_non_ui_literal(text):
                continue
            if "<" in text and ">" in text:
                _emit_html_fragment_prose(
                    text, rel, lineno, result,
                    reason="innerHTML/outerHTML template not routed through i18n.t()",
                    confidence="high",
                )
            elif _is_prose(text):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno,
                    "innerHTML/textContent template literal not routed through i18n.t()",
                    confidence="high",
                ))

        for _q, html in _INNER_HTML_QUOTED.findall(cleaned):
            html = html.strip()
            if not html or is_non_ui_literal(html):
                continue
            if "<" in html:
                _emit_html_fragment_prose(
                    html, rel, lineno, result,
                    reason="quoted innerHTML/outerHTML not routed through i18n.t()",
                    confidence="high",
                )
            elif _is_ui_copy(html, widget=True):
                conf = grade(html)
                result.hardcoded.append(HardcodedString(
                    html, rel, lineno,
                    "quoted innerHTML/outerHTML not routed through i18n.t()",
                    confidence=conf,
                ))

        for _q, text in _TEXT_ASSIGN.findall(line):
            text = text.strip()
            if is_listener_event_arg(line, text) or is_non_user_attr_value(line, text):
                continue
            if _is_ui_copy(text, widget=True):
                conf = grade(text)
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno,
                    "textContent/innerText assignment not routed through i18n",
                    confidence=conf,
                ))

        for tag, text in _EL_CALL.findall(line):
            text = text.strip()
            if not _is_ui_copy(text, widget=True):
                continue
            conf = grade(text)
            result.hardcoded.append(HardcodedString(
                text, rel, lineno,
                f'el("{tag}", …) user-facing label — route through uiT/data-i18n',
                confidence=conf,
            ))

        for tag, text in _EL_CALL_CONCAT.findall(line):
            # Leading fragment of ``"No " + x`` is not actionable; only
            # multi-word prose prefixes are worth a hit.
            text = text.strip()
            if not _is_prose(text):
                continue
            result.hardcoded.append(HardcodedString(
                text, rel, lineno,
                f'el("{tag}", …) concatenated label — route through uiT/data-i18n',
                confidence="high",
            ))

        for _q, text in _CREATE_TEXT.findall(line):
            text = text.strip()
            # Leading space used when joining checkbox labels: " " + expr
            if text in {" ", "  ", ": ", " · ", " — ", " / "}:
                continue
            if not _is_ui_copy(text, widget=True):
                continue
            conf = grade(text)
            result.hardcoded.append(HardcodedString(
                text, rel, lineno,
                "createTextNode(…) user-facing label — route through uiT/data-i18n",
                confidence=conf,
            ))

        for _q, text in _DIALOG.findall(line):
            text = text.strip()
            if _is_ui_copy(text, widget=True):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno,
                    "confirm/alert/prompt string not routed through i18n",
                    confidence="high",
                ))

        for attr, value in _USER_ATTR_PLAIN.findall(line):
            value = value.strip()
            if is_non_ui_literal(value):
                continue
            if _is_prose(value):
                result.hardcoded.append(HardcodedString(
                    value, rel, lineno,
                    f"{attr}= attribute in JS not routed through i18n.t()",
                    confidence="high",
                ))


def _split_key(key: str) -> tuple[str, str]:
    """Split 'nav.queue' → ('nav', 'queue'), 'queue' → ('', 'queue')."""
    if "." in key:
        ns, bare = key.split(".", 1)
        return ns, bare
    return "", key
