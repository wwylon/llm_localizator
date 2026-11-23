"""Whether one JavaScript literal is user-visible copy, from its context (split from js_context, M3).

The call and property tables (``UI_CALLS``, ``NON_UI_CALLS``, ``UI_NAMES``, ``NON_UI_NAMES``), the copy-shape checks,
``judge`` itself, the file-local UI helper detection (``local_ui_sinks``) and the de-duplicating hit recorder shared
with the markup-text pass.
"""

from __future__ import annotations

import re

from .base import HardcodedString, ScanResult, _locale_like
from .js_tokenizer import _HOLE, JsLiteral
from .negatives import is_non_ui_literal
from .prose import grade, is_lone_word, is_prose, is_short_label
from .usage_calls import is_routed_callee

__all__ = ["judge", "local_ui_sinks", "UI_CALLS", "NON_UI_CALLS", "UI_NAMES", "NON_UI_NAMES"]

#: ROUTED_CALLS (already routed through the i18n layer) is shared: scan/usage_calls.py (ADR-120).
#: Last segment of a callee whose string arguments are not product copy.
NON_UI_CALLS = frozenset({
    "plausible", "trackEvent", "track", "trackPageview", "gtag", "logEvent", "sendEvent", "capture",
    "querySelector", "querySelectorAll", "getElementById", "getElementsByClassName",
    "getElementsByTagName", "closest", "matches", "addEventListener", "removeEventListener",
    "dispatchEvent", "on", "off", "once", "emit", "add", "remove", "toggle", "contains",
    "setAttribute", "getAttribute", "removeAttribute", "hasAttribute", "setProperty",
    "getPropertyValue", "fetch", "require", "import", "getItem", "setItem", "removeItem",
    "createElement", "createElementNS", "createEvent", "matchMedia", "includes", "startsWith",
    "endsWith", "indexOf", "lastIndexOf", "split", "join", "replace", "replaceAll", "test",
    "match", "search", "Symbol", "postMessage", "URL", "URLSearchParams", "Date", "RegExp",
    "toLocaleString", "toLocaleDateString", "toLocaleTimeString", "NumberFormat",
    "DateTimeFormat", "Intl", "parseInt", "parseFloat", "Number", "parse", "stringify",
    "get", "set", "has", "delete", "post", "put", "patch", "request", "open", "send",
    "setHeader", "append", "getContext", "useState", "useRef", "useMemo", "useCallback",
    "useEffect", "useQuery", "useMutation", "localeCompare", "padStart", "padEnd",
    "log", "debug", "info", "warn", "trace", "assert", "group", "time", "timeEnd",
    "cn", "clsx", "cva", "twMerge", "classNames", "css", "keyframes", "styled",
    "redirect", "push", "navigate", "router.push", "href", "route", "invoke", "call",
    "execute", "query", "prepare", "exec", "spawn", "writeFile", "readFile", "join",
    "resolve", "dirname", "basename", "extname", "existsSync", "mkdir", "unlink",
    "getElementsByName", "attr", "data", "prop", "css", "addClass", "removeClass",
    "select", "selectAll", "style", "classed", "transition", "ease", "font", "fillStyle",
    "measureText", "Error.captureStackTrace", "mark", "measure", "defineProperty",
})
#: Callees whose string arguments are shown to the user.
UI_CALLS = frozenset({
    "alert", "confirm", "prompt", "toast", "toast.success", "toast.error", "toast.info",
    "toast.warning", "toast.message", "showToast", "openAlert", "openConfirm", "showError",
    "setError", "setStatus", "setMessage", "setNotice", "notify", "Notification",
    "message.success", "message.error", "message.info", "message.warning", "say",
    "createTextNode", "text", "html", "tooltip", "setTitle", "setLabel", "fillText",
    "strokeText", "dialog", "showDialog", "modal", "banner", "flash",
})
#: Property / attribute / assignment names whose value is user copy.
UI_NAMES = frozenset({
    "label", "labels", "title", "text", "desc", "description", "placeholder", "message",
    "msg", "tooltip", "hint", "help", "helpText", "caption", "heading", "subtitle",
    "summary", "header", "headline", "error", "errorMessage", "confirm", "okLabel",
    "cancelLabel", "confirmLabel", "buttonText", "emptyText", "empty", "note", "notice",
    "short", "long", "action", "impact", "linkText", "content", "body", "alt",
    "aria-label", "ariaLabel", "aria-description", "textContent", "innerText", "nodeValue",
    "legend", "prefix", "suffix", "unit", "status", "statusText", "detail", "details",
    "warning", "info", "success", "subject", "sideLabels", "trickLabels", "displayName",
    "headerName", "tab", "tabs", "name", "labelPl", "labelEn", "question", "answer",
})
#: Names whose value is an identifier, never copy.
NON_UI_NAMES = frozenset({
    "statusMessage",   # (``statusText`` is in UI_NAMES, which wins; L27)
    "id", "key", "type", "kind", "value", "className", "class", "href", "src", "url",
    "path", "icon", "color", "variant", "size", "method", "mode", "role", "ref", "field",
    "format", "lang", "locale", "dir", "target", "rel", "style", "width", "height",
    "htmlFor", "for", "name_id", "slug", "code", "action_id", "event", "data-testid",
    "testId", "accept", "autoComplete", "autocomplete", "inputMode", "pattern", "step",
    "min", "max", "align", "justify", "side", "position", "theme", "fontFamily", "font",
    "fill", "stroke", "d", "viewBox", "xmlns", "transform", "display", "cursor",
    "background", "border", "margin", "padding", "gap", "radius", "weight", "sort",
    "order", "query", "q", "endpoint", "api", "route", "redirect", "storageKey", "cacheKey",
    "mime", "contentType", "encoding", "charset", "sameSite", "domain", "host", "origin",
    "env", "provider", "model", "engine", "backend", "selector", "tag", "tagName", "as",
    "layout", "loading", "decoding", "referrerPolicy", "crossOrigin", "integrity",
    "@type", "@context", "@id", "robots", "gridTemplateColumns", "gridTemplateAreas",
    "boxShadow", "fontWeight", "textTransform", "whiteSpace", "objectFit", "sizes",
})
_SELECTORISH = re.compile(r"^[.#\[:]?[a-z][\w-]*(?:[.#\[:>\s~+][\w\-=\"'\]()]*)*$")
_CODEISH = re.compile(r"[;{}]|=>|\$\(|^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)\b|\bvoid\s+main\b|gl_|vec[234]\b")
_CAP_LABEL = re.compile(r"^[A-ZÀ-ÖØ-ÞĀ-ſƀ-ɏḀ-ỿ][\w'’.-]*(?:\s+[\w'’.&/-]+){0,5}[.!?:…]?$")
_WORD_SPLIT = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def _words(text: str) -> str:
    return " ".join(w.lower() for w in _WORD_SPLIT.findall(text))


#: UI fields that merely contain "prompt": ``promptText``, ``confirmPrompt``, ``promptLabel`` (L26).
_UI_PROMPT_NAME = re.compile(r"(?i)(?:text|label|title|message|hint|placeholder|caption)$|^(?:confirm|input|dialog)")


def _llm_prompt_name(name: str) -> bool:
    """``systemPrompt``, ``NEWS_PROMPT``: an LLM prompt, not shown. ``prompt`` alone and prompt UI fields are not."""
    return bool(re.search(r"prompt", name, re.I)) and name.lower() != "prompt" and not _UI_PROMPT_NAME.search(name)


def _base(callee: str | None) -> str:
    if not callee:
        return ""
    return callee.rsplit(".", 1)[-1]


def _is_ideograph(t: str) -> bool:
    """A single Han ideograph, kana or Hangul syllable."""
    import unicodedata

    return len(t) == 1 and unicodedata.category(t) == "Lo" and ord(t) >= 0x1100


_SIMPLE_PLACEHOLDER = re.compile(r"\{\w{1,30}\}")


def _without_placeholders(t: str) -> str:
    """``Search for "{q}"`` has braces but is a message: blank simple ``{name}`` / ``{0}`` holes when real words surround them.

    A string of only holes, or holes with at most one word, stays as it was (``{a} {b}`` is more likely code or CSS).
    """
    if "{" not in t:
        return t
    blanked = _SIMPLE_PLACEHOLDER.sub("x", t)
    words = [w for w in re.findall(r"[^\W\d_]{2,}", blanked) if w != "x"]
    return blanked if len(words) >= 2 else t


def _is_copy_shape(text: str) -> bool:
    t = text.strip()
    if t.endswith(";") and any(ord(ch) > 0x2FF and ch.isalpha() for ch in t):
        t = t[:-1] + "?"  # Greek writes its question mark as ';'
    if not any(ch.isalpha() for ch in t) or (len(t) < 2 and not _is_ideograph(t)):
        return False  # one Han character or Hangul syllable is a whole label ("删", "예")
    if is_non_ui_literal(t) or _CODEISH.search(_without_placeholders(t)):
        return False
    if " " not in t and _SELECTORISH.match(t) and not t[:1].isupper():
        return False
    words = t.split()
    if len(words) > 1 and all(re.fullmatch(r"!?-?[a-z][\w:/.\[\]()#%,'=&>*-]*", w) for w in words) and any(
        re.search(r"[-_\d:\[]", w) for w in words
    ):
        return False  # CSS class list ("btn btn-primary", "flex gap-2 md:grid")
    if re.match(r"^(?:https?:|mailto:|data:|/|\./|\.\./|#[\w-]|[\w.-]+\.(?:js|ts|css|png|svg|json|html)$)", t):
        return False
    if re.fullmatch(r"[A-Z0-9_]{2,}", t) or re.fullmatch(r"[a-z][a-zA-Z0-9]*[A-Z][\w]*", t):
        return False  # CONST_CASE / camelCase identifiers
    if re.fullmatch(r"[\w.-]+(?:[/:][\w.-]+)+", t):
        return False  # keys, paths, mime types, event names ("app/user.created")
    if _NOT_COPY.search(t):
        return False
    return True


_NOT_COPY = re.compile(
    r"^[\w.+-]+@[\w-]+\.[\w.]+$"                      # e-mail address
    r"|^[A-Z0-9]+(?:[-_][A-Z0-9]+)+$"                 # ids: OWN-MAREK, T-001
    r"|^\w+(?:,\w+){2,}$"                             # CSV header row
    r"|\(\s*(?:min|max|prefers)-[\w-]+\s*:"           # media query / sizes
    r"|^(?:[\d.]+(?:px|vw|vh|rem|em|%)[\s,]*)+$"      # CSS lengths
    r"|^[MLHVCSQTAZmlhvcsqtaz][\d\s,.-]+(?:[MLHVCSQTAZmlhvcsqtaz][\d\s,.-]+)+$"  # SVG path data
    r"|\bvar\(--|\b(?:rgba?|hsla?|calc|url|linear-gradient)\(|#[0-9a-fA-F]{3,8}\b"  # CSS values
    r"|\b\d+(?:\.\d+)?(?:px|fr|ms|deg)\b|^(?:\d[\d.]*[a-z%]*\s+)*(?:solid|dashed|dotted)\b"  # number then unit: no overlap, no backtracking
    r"|^use (?:client|server|strict)$"                # directive prologue
    r"|^(?:X|[A-Z][a-z]+)(?:-[A-Z][\w]*)+$"           # HTTP header names (X-LLM-Token, Content-Type)
    r"|\b[\w:-]+=\"[^\"]*\"|\b[\w:-]+='[^']*'"        # markup attribute syntax (SVG/HTML strings)
    r"|^\$ \w"                                        # shell command example
    r"|^[\d.,~≈]*\s*(?:[KMGTP]i?B|[kMG]?Hz|ms|fps|°C?|px)(?:\s*/)?\s*$"  # unit suffixes (GiB, MHz)
    r"|^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+$"            # PascalCase identifiers (AuthError)
    r"|^[A-Za-z]*[a-z][A-Z][A-Za-z]*-[A-Za-z0-9-]+$"   # camelCase-with-dash ids (CodeMirror-linenumbers)
    r"|^(?i:ctrl|cmd|command|alt|option|shift|meta|control)\s*\+\s*\S+$"  # keyboard shortcuts
)
#: Severity words passed as the second argument of a toast/notify call (v70).
_TOAST_KINDS = frozenset({
    "err", "error", "info", "warn", "warning", "ok", "success", "danger", "fail", "failure",
    "notice", "debug", "primary", "secondary", "neutral",
})
#: ``{en: "…", pl: "…"}`` — copy translated in the source itself, not a leftover.
_ELEMENT_FACTORIES = frozenset({"React.createElement", "createElement", "h", "jsx", "_jsx", "jsxs", "_jsxs"})
_LOCALE_KEY = re.compile(r"^[a-z]{2}(?:[-_][A-Za-z]{2,4})?$")


def judge(lit: JsLiteral, text: str, sinks: dict[str, set[int]] | None = None) -> tuple[str, str] | None:
    """(confidence, reason) for one literal (or template static part), or None."""
    callee = lit.callee or ""
    base = _base(callee)
    if (sinks and callee in sinks and lit.arg in sinks[callee] and not lit.routed_fallback
            and callee.lower() not in _LOG_HELPERS):
        shown = " ".join(text.replace(_HOLE, " … ").split())
        if _SINK_VALUE.fullmatch(shown) or _SINK_CSS.search(shown):
            return None  # a quantity, unit, short acronym or CSS value, not copy
        # Inside a known sink a lighter shape check is enough: prose may contain "; ".
        if re.search(r"[A-Za-z]{2,}", shown) and not is_non_ui_literal(shown) and not (
                " " not in shown and _SELECTORISH.match(shown)):
            concat = "+" in (lit.prev, lit.next)
            if concat and len(shown.split()) < 2 and not shown.endswith((":", "…")):
                return None
            conf = grade(shown, label=(_CAP_LABEL.match,))
            return conf, f"{callee}(…) puts this text on screen (helper defined in this file)"
    if is_routed_callee(callee) or base in {"t", "uiT", "$t", "gettext", "formatMessage"}:
        return None
    if lit.routed_fallback:
        return None
    if callee == "${":
        callee, base = "", ""
    if lit.quote != "tpl" and lit.next == ":" and lit.prev in ("{", ",", ""):
        return None  # object key
    if lit.prev in ("===", "!==", "==", "!=", "case", "in", "instanceof") or lit.next in ("===", "!==", "==", "!=", "in"):
        return None
    if lit.prev in ("import", "from", "require", "export") or callee in ("require", "import"):
        return None
    if lit.prev == "|" or lit.next == "|" or lit.prev == "&" or lit.next == "&":
        return None  # TS union / intersection types
    if callee in _ELEMENT_FACTORIES:
        # React.createElement(tag, props, ...children): string children are text nodes.
        if lit.arg < 2:
            return None
        t = " ".join(text.split())
        if not _is_copy_shape(t):
            return None
        conf = grade(t, label=(_CAP_LABEL.match,))
        return conf, "text child of an element factory (createElement/h)"
    # A full callee listed as UI (``message.success``) beats a non-UI last segment (M2: the base check won first).
    if callee.startswith("console.") or (base in NON_UI_CALLS and callee not in UI_CALLS):
        return None
    name = lit.name
    if name and name not in UI_NAMES and (name in NON_UI_NAMES or name.startswith(("data-", "on"))):
        return None
    if name and lit.prev == ":" and _LOCALE_KEY.match(name) and _locale_like(name):
        return None  # in-source translation table (L26: a known language code, not ``ok:`` / ``by:``)
    if name and _llm_prompt_name(name):
        return None  # LLM prompt text (systemPrompt, NEWS_PROMPT), not shown in the UI
    if lit.quote == "tpl-text":
        shown = " ".join(text.replace(_HOLE, " … ").split())
        if base in ("Error", "TypeError", "RangeError", "HTTPException"):
            return "low", "error message template; route through t() if it reaches the screen"
        if callee in UI_CALLS or base in UI_CALLS or (name and name in UI_NAMES):
            return "high", "template literal with text around ${…} shown to the user"
        if is_prose(text.replace(_HOLE, " ")) or lit.prev in (
                "=", "+=", "return", "?", ":", "(", ",", "=>", "||", "??", "["):
            return "medium", "template literal with text around ${…}; use one ICU message"
        return ("low", "template literal with text") if shown else None
    t = " ".join(text.split())
    if lit.arg >= 1 and t in _TOAST_KINDS and (callee in UI_CALLS or base in UI_CALLS):
        return None  # ``showToast(msg, 'err')``: the severity argument, not copy
    if (callee in UI_CALLS or base in UI_CALLS) and (is_lone_word(t) or is_short_label(t)):
        # ``alert("nedelja")``: a call that shows text to a person makes even a lone lower-case word copy
        # (Spanish, Catalan, Finnish and others write month, day and language names in lower case).
        return "medium", f"{base or callee}(…) shows this text to the user"
    if not _is_copy_shape(t):
        return None
    prose = is_prose(t)
    label = bool(_CAP_LABEL.match(t))
    ui_call = callee in UI_CALLS or base in UI_CALLS
    ui_name = bool(name) and name in UI_NAMES
    if ui_call:
        return ("high" if prose or label else "medium", f"{base or callee}(…) shows this text to the user")
    if ui_name:
        if prose:
            return "high", f"'{name}' holds user-visible copy"
        if label or t[:1].isalpha():
            return "medium", f"'{name}' holds user-visible copy"
        return None
    if base in ("Error", "TypeError", "RangeError", "HTTPException"):
        return ("low", "error message; route through t() if it reaches the screen") if prose else None
    if name and _words(name) and _words(name) == _words(t):
        return "medium", f"member '{name}' repeats its own label; use a message key"
    concat = "+" in (lit.prev, lit.next)
    if concat and len(t.split()) < 2 and not t.endswith((".", "!", "?", ":", "…")):
        return None  # orphan word of a concatenation is not actionable on its own
    if prose:
        return "medium", "string literal reads as user-visible prose"
    if label and lit.prev in ("?", ":", "return", "||", "??", "+", "[", ",", "=>", "("):
        return "medium", "capitalised label in a value position"
    if label:
        return "low", "capitalised literal"
    return None


# ---- local UI sinks: helpers defined in the same file that put a parameter on screen

#: Helpers that write a log panel, not product UI.
_LOG_HELPERS = frozenset({"log", "debug", "trace", "print", "dbg", "logline", "appendlog", "writelog"})
#: "0.0 GiB", "… MHz", "RAM", "12%": values and units, not sentences.
_SINK_VALUE = re.compile(r"[\d.,\s…+\-]*[A-Za-z%]{0,4}[\s…]*")
_SINK_CSS = re.compile(r"var\(|^#[0-9a-fA-F]{3,8}$|\b(?:rgb|hsl)a?\(")

_FUNC_DEF = re.compile(
    r"(?:\bfunction\s+([A-Za-z_$][\w$]*)\s*\(([^()]*)\)\s*\{"
    r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:function\s*)?\(([^()]*)\)\s*(?:=>)?\s*(\{)?)")
_SINK_USES = (
    r"\.(?:textContent|innerText|innerHTML|outerHTML|title|placeholder|ariaLabel|nodeValue)\s*\+?=\s*[^;\n]*\b{p}\b",
    r"createTextNode\(\s*[^)]*\b{p}\b",
    r"setAttribute\(\s*['\"](?:title|aria-label|placeholder|alt)['\"]\s*,[^)]*\b{p}\b",
    r"\b(?:alert|confirm|toast|showToast|notify|openAlert|openConfirm)\s*\([^)]*\b{p}\b",
)


def _body(text: str, start: int, brace: bool) -> str:
    """The function body from ``start``: to the matching brace, or one arrow expression."""
    if not brace:
        end = len(text)
        for stop in (";\n", "\n"):
            k = text.find(stop, start)
            if k >= 0:
                end = min(end, k)
        return text[start:end]
    depth, j, limit = 1, start, min(len(text), start + 4000)
    while j < limit and depth:
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        j += 1
    return text[start:j]


def local_ui_sinks(text: str) -> dict[str, set[int]]:
    """Helpers in this file whose parameter reaches the screen: name -> argument indexes.

    ``const set = (id, txt) => { … e.textContent = txt; }`` makes ``set('x', 'Label')``
    a UI call for argument 1; ``const add = (k, v) => rows.push(`<div>${escHtml(k)}…`)``
    makes argument 0 of ``add`` one.
    """
    sinks: dict[str, set[int]] = {}
    for m in _FUNC_DEF.finditer(text):
        name = m.group(1) or m.group(3)
        params = m.group(2) if m.group(1) else m.group(4)
        brace = bool(m.group(1)) or bool(m.group(5))
        if not name or params is None:
            continue
        body = _body(text, m.end(), brace)
        html_tpl = [t for t in re.findall(r"`[^`]*`", body) if "<" in t]
        for k, raw in enumerate(params.split(",")):
            param = raw.strip().split("=")[0].strip()
            if not re.fullmatch(r"[A-Za-z_$][\w$]*", param or ""):
                continue
            esc = re.escape(param)
            hit = any(re.search(pat.replace("{p}", esc), body) for pat in _SINK_USES)
            if not hit:
                hit = any(re.search(r"\$\{[^}]*\b" + esc + r"\b", t) for t in html_tpl)
            if hit:
                sinks.setdefault(name, set()).add(k)
    return sinks


class _Seen(set):
    """``(line, text)`` pairs already reported, plus a per-line text index (M4 P1: no linear scan per hit)."""

    def __init__(self, items=()) -> None:
        super().__init__(items)
        self.by_line: dict[int, list[str]] = {}
        for ln, txt in self:
            self.by_line.setdefault(ln, []).append(txt)


def _line_index(seen: set) -> dict[int, list[str]]:
    if isinstance(seen, _Seen):
        return seen.by_line
    out: dict[int, list[str]] = {}  # plain set from an outside caller: build once per call (old cost)
    for ln, txt in seen:
        out.setdefault(ln, []).append(txt)
    return out


def _add(result: ScanResult, seen: set,t: str, rel: str, line: int, conf: str, reason: str) -> None:
    key = (line, t)
    if key in seen:
        return
    by_line = _line_index(seen)
    if any(t in txt or txt in t for txt in by_line.get(line, ())):
        return  # a sink rule already reported this text on this line
    seen.add(key)
    by_line.setdefault(line, []).append(t)
    result.hardcoded.append(HardcodedString(t, rel, line, reason, confidence=conf))
