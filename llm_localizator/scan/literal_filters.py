"""Developer-only code around string literals, for the shared literal detector.

Previews, annotation arguments, logging calls (including wrapped and concatenated ones), constants that name an
identifier, enum raw values and ``comment:`` arguments never reach a person. Each helper keeps line numbers intact.
"""

from __future__ import annotations

from .views import blank_spans

import re

__all__ = ["blank_dev_blocks", "log_lines", "is_dev_context"]

_PREVIEW_START = {
    "kotlin": re.compile(r"(?m)^[ \t]*@(?:\w+\.)?Preview\w*\b(?:\([^)]*\))?[ \t]*\n(?:[ \t]*@\w+(?:\([^)]*\))?[ \t]*\n)*[ \t]*(?:private[ \t]+|internal[ \t]+)?fun[ \t]+\w+"),
    "swift": re.compile(r"(?m)^[ \t]*(?:#Preview\b[^{\n]*|(?:struct|class)[ \t]+\w*Preview\w*[ \t]*:[^{\n]*PreviewProvider[^{\n]*)(?=\{)"),
}
_ANNOTATION_LINE = re.compile(r"(?m)^[ \t]*@(?:Query|RawQuery|Entity|Database|ColumnInfo|SerializedName|JsonProperty|SerialName|Json|Table|Column|JoinColumn|RequestMapping|GetMapping|PostMapping|Value|Qualifier|Named|Test\w*|Suppress\w*|JvmName|SuppressLint|Deprecated)\b[^\n]*(?:\n[ \t]+[^\n@]*\)[ \t]*(?=\n))?")
_CONST_DECL = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|final|const|override|@JvmField|@JvmStatic)\s+)*"
    r"(?:(?:val|var|let|String|string|auto|char\s*\*|const\s+char\s*\*|std::string)\s+)?[A-Z][A-Z0-9_]{2,}\s*(?::\s*\w+\s*)?=\s*[\"'`]"
)
_PREVIEW_NAMED = re.compile(r"(?m)^[ \t]*(?:private[ \t]+|internal[ \t]+)?(?:fun|val)[ \t]+\w*Preview\w*\b[^\n{]*")
#: Rust unit tests: ``#[cfg(test)] mod tests { … }``.
_CFG_TEST = re.compile(r"(?m)^[ \t]*#\[cfg\(test\)\][ \t]*\n(?:[ \t]*#\[[^\n]*\][ \t]*\n)*[ \t]*(?:pub[ \t]+)?mod[ \t]+\w+")
_ENUM_RAW =re.compile(r"""^\s*case\s+\w+\s*=\s*["']""")
_COMMENT_ARG = re.compile(r"""\bcomment\s*:\s*$""")
_IDENT = re.compile(r"^[\w.:/-]+$")


def _match_brace(text: str, open_at: int) -> int:
    depth, i, n = 0, open_at, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] not in (c, "\n"):
                j += 2 if text[j] == "\\" else 1
            i = j
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def blank_dev_blocks(text: str, lang_id: str) -> str:
    """Blank preview functions and annotation lines (``@Preview fun``, ``#Preview { }``, ``@Query("…")``).

    Spans are collected first and blanked in one pass (the old loop rebuilt the whole text once per match).
    """
    spans: list[tuple[int, int]] = []
    pattern = _PREVIEW_START.get(lang_id)
    if pattern is not None:
        for m in pattern.finditer(text):
            brace = text.find("{", m.end())
            equals = text.find("=", m.end())
            if brace < 0 or (0 <= equals < brace and "\n" in text[m.end():brace] and "(" not in text[equals:brace]):
                continue
            spans.append((m.start(), _match_brace(text, brace) + 1))
    if lang_id in {"kotlin", "java", "scala"}:
        spans.extend(m.span() for m in _ANNOTATION_LINE.finditer(text))
    if lang_id == "kotlin":
        # ``fun FooPreview()``, ``val BarPreviewSample = …``: preview helpers named, not annotated.
        for m in _PREVIEW_NAMED.finditer(text):
            brace = text.find("{", m.end())
            nl = text.find("\n", m.end())
            if brace >= 0 and (nl < 0 or brace <= nl + 200):
                spans.append((m.start(), _match_brace(text, brace) + 1))
    if lang_id == "rust":
        for m in _CFG_TEST.finditer(text):
            brace = text.find("{", m.end())
            if brace >= 0:
                spans.append((m.start(), _match_brace(text, brace) + 1))
    return blank_spans(text, spans)


_CLAP_ATTR = re.compile(r"^\s*#\[(?:arg|clap|command)\b")


def clap_doc_comments(lines: list[str]) -> list[tuple[int, str]]:
    """``/// Text`` on a clap field or command: it becomes the ``--help`` description a person reads."""
    found: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("///"):
            j, parts = i, []
            while j < len(lines) and lines[j].lstrip().startswith("///"):
                parts.append(lines[j].lstrip()[3:].strip())
                j += 1
            nxt = [ln for ln in lines[j:j + 3]]
            if any(_CLAP_ATTR.match(ln) for ln in nxt):
                text = " ".join(p for p in parts if p)
                if len(text) >= 3 and any(ch.isalpha() for ch in text):
                    found.append((i + 1, text))
            i = j
        else:
            i += 1
    return found


#: A quoted string on one line, escapes included (its parentheses are text, not code).
_QUOTED_SPAN = re.compile(r""""(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\\n]|\\.)*`""")


def log_lines(lines: list[str]) -> set[int]:
    """1-based numbers of every line inside a logging call, so wrapped ``Log.d(TAG, "a" +\\n "b")`` stays developer text."""
    from .literals import _LOG_START

    marked: set[int] = set()
    i = 0
    while i < len(lines):
        if _LOG_START.match(lines[i]):
            depth, j = 0, i
            while j < len(lines):
                code = _QUOTED_SPAN.sub('""', lines[j])   # M2: ``log("Saved (draft")`` must not open a paren
                depth += code.count("(") - code.count(")")
                marked.add(j + 1)
                if depth <= 0 or j - i > 12:
                    break
                j += 1
            i = j
        i += 1
    return marked


#: Calls whose message is for the developer: ``.expect("…")``, ``panic!("…")``, ``assert!(…, "…")``, animation ``label = "…"``.
_DEV_CALL = re.compile(
    r"\.expect\(|\.unwrap_or_else\(|\b(?:panic|unreachable|todo|unimplemented|assert|assert_eq|debug_assert)!\s*\(|"
    r"\b(?:animate\w+AsState|animate(?:Float|Color|Dp|Int|Value)|rememberInfiniteTransition|AnimatedContent|Crossfade|"
    r"updateTransition|AnimatedVisibility|AnimatedContentTransitionScope)\b[^\n]*\blabel\s*=|\bfail\("
)


def is_dev_context(line: str, literal: str) -> bool:
    """A literal that is an enum raw value, an identifier constant, a ``comment:`` argument, or a developer message."""
    if _ENUM_RAW.match(line):
        return True
    pos0 = line.find(literal) if literal else -1
    if _DEV_CALL.search(line[:pos0] if pos0 > 0 else line):
        return True
    if _CONST_DECL.match(line) and _IDENT.match(literal.strip()):
        return True
    pos = line.find(literal) if literal else -1
    return pos > 0 and bool(_COMMENT_ARG.search(line[:pos]))
