"""Indentation-based Ruby templates: HAML (``.haml``) and Slim (``.slim``).

Neither is HTML, so the HTML rules cannot read them directly. Each file is turned into two views with the same
line numbers, the way ``sfc.py`` splits a Vue file:

- a **markup view**: tag lines become ``<tag class="…" attr="…">text</tag>``, plain text lines are wrapped in the
  tag they sit under, ``#{…}`` becomes the slot word, comments and script/style filters are blanked;
- a **Ruby view**: the code after ``=``, ``!=``, ``-`` (and their continuation lines), so ``link_to "Sign up"``,
  ``form.submit "Save"`` and ``f.label :email, "Email address"`` go through the Ruby literal pass, where
  ``t(".key")`` is routed and Rails view helpers are UI sinks.

Literal attribute values (``{ placeholder: "Search" }``, ``(title="About")``, ``title="About"``) go into the markup
view as HTML attributes, so the HTML attribute rules decide which are visible; ``class`` or ``type`` values never are.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ScanResult, relative_posix
from .views import MarkupView, scan_markup_view

__all__ = ["haml_views", "slim_views", "scan_indent_file"]

_INTERP = re.compile(r"#\{(?:[^{}]|\{[^{}]*\})*\}")
#: ``key: "value"``, ``:key => "value"``, ``"key" => "value"`` inside a Ruby attribute hash.
_HASH_PAIR = re.compile(
    r"""(?:(?<![\w:])([A-Za-z_][\w-]*):\s*|:([A-Za-z_][\w-]*)\s*=>\s*|["']([\w:-]+)["']\s*=>\s*)"""
    r"""(?:"((?:\\.|[^"\\#]|#(?!\{))*)"|'((?:\\.|[^'\\])*)')"""
)
#: ``name="value"`` / ``name='value'`` (HAML ``(…)`` attributes, Slim attributes).
_HTML_PAIR = re.compile(r"""(?<![\w:@.-])([\w:@.-]+)\s*=\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)')""")
_RAW_TAGS = {"script", "style", "pre", "code", "textarea"}
_HIDDEN_FILTERS = {"javascript", "css", "scss", "sass", "less", "coffee", "coffeescript", "erb", "cdata", "escaped"}
_TEXT_FILTERS = {"plain", "markdown", "textile", "preserve"}


def _slot_text(text: str) -> str:
    return MarkupView.slot_text(_INTERP, text)


def _attr(name: str, value: str) -> str:
    value = _slot_text(value).replace('"', "&quot;")
    return f' {name}="{value}"'


def _balanced(text: str, i: int, opener: str, closer: str) -> int:
    """Index after the bracket that closes ``text[i]`` (``len(text)`` when it is not closed on this line)."""
    depth, quote = 0, ""
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _hash_attrs(chunk: str) -> str:
    """Literal string pairs of a Ruby hash as HTML attributes; nested hashes (``data: {…}``) are skipped."""
    out, depth = [], 0
    pos = 0
    for m in _HASH_PAIR.finditer(chunk):
        depth += chunk.count("{", pos, m.start()) - chunk.count("}", pos, m.start())
        pos = m.start()
        if depth > 1:
            continue
        name = m.group(1) or m.group(2) or m.group(3)
        value = m.group(4) if m.group(4) is not None else m.group(5)
        out.append(_attr(name, value))
    return "".join(out)


def _html_attrs(chunk: str) -> str:
    return "".join(_attr(m.group(1), m.group(2) if m.group(2) is not None else m.group(3))
                   for m in _HTML_PAIR.finditer(chunk))


class _Views:
    """Markup and Ruby lines being built, plus the open-tag stack used to wrap plain text."""

    def __init__(self, n: int) -> None:
        self.markup = [""] * n
        self.ruby = [""] * n
        self.stack: list[tuple[int, str, str]] = []   # (indent, tag, class)

    def parent(self, indent: int) -> tuple[str, str]:
        while self.stack and self.stack[-1][0] >= indent:
            self.stack.pop()
        return (self.stack[-1][1], self.stack[-1][2]) if self.stack else ("p", "")

    def interp(self, i: int, text: str) -> None:
        """``#{link_to "Sponsor", url}`` inside text: the expression is code, its literals go to the Ruby view."""
        exprs = [m.group()[2:-1] for m in _INTERP.finditer(text)]
        if exprs:
            self.ruby[i] = (self.ruby[i] + "; " if self.ruby[i] else "") + "; ".join(exprs)

    def text(self, i: int, indent: int, text: str) -> None:
        tag, cls = self.parent(indent)
        if tag in _RAW_TAGS or not text.strip():
            return
        self.interp(i, text)
        cls_attr = f' class="{cls}"' if cls else ""
        self.markup[i] = f"<{tag}{cls_attr}>{_slot_text(text.strip())}</{tag}>"

    def element(self, i: int, indent: int, tag: str, cls: str, attrs: str, body: str | None, code: str | None) -> None:
        self.parent(indent)
        self.stack.append((indent, tag, cls))
        cls_attr = f' class="{cls}"' if cls else ""
        if code is not None:
            self.ruby[i] = code
            inner = MarkupView.SLOT
        else:
            inner = "" if tag in _RAW_TAGS else _slot_text((body or "").strip())
            if inner:
                self.interp(i, body or "")
        self.markup[i] = f"<{tag}{cls_attr}{attrs}>{inner}</{tag}>"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _code_continues(code: str) -> bool:
    """A Ruby line in a template continues on the next line after a trailing comma, pipe or open bracket."""
    s = code.rstrip()
    return s.endswith((",", "|", "(", "[", "{", "\\")) and not s.endswith("do |")


_HAML_HEAD = re.compile(r"(%[\w:-]+)?((?:[.#][\w-]+)*)")


def haml_views(text: str) -> tuple[str, str]:
    """``(markup, ruby)`` views of a HAML file, same line count."""
    lines = text.split("\n")
    v = _Views(len(lines))
    block: tuple[int, str] | None = None   # (indent, kind) of a comment / filter block
    cont = ""                              # "ruby" or "hash" while a statement spills onto the next line
    hash_depth = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        ind = _indent(line)
        if block and ind > block[0]:
            if block[1] == "ruby":
                v.ruby[i] = line
            elif block[1] == "text":
                v.text(i, block[0] + 1, stripped)
            continue
        block = None
        if cont == "ruby":
            v.ruby[i] = line
            cont = "ruby" if _code_continues(line) else ""
            continue
        if cont == "hash":
            v.markup[i] = f"<span{_hash_attrs(line)}></span>" if _hash_attrs(line) else ""
            hash_depth += line.count("{") - line.count("}")
            cont = "hash" if hash_depth > 0 else ""
            continue
        if stripped.startswith("-#") or stripped.startswith("/"):
            block = (ind, "hidden")
            continue
        if stripped.startswith("!!!"):
            continue
        if stripped.startswith(":"):
            name = stripped[1:].split()[0] if stripped[1:].split() else ""
            block = (ind, "ruby" if name == "ruby" else "text" if name in _TEXT_FILTERS else "hidden")
            continue
        if stripped.startswith(("==", "!==", "&==")):
            v.text(i, ind, stripped.lstrip("!&="))   # interpolated plain text, not code
            continue
        if stripped[0] in "=-~" or stripped.startswith(("!=", "&=")):
            code = stripped.lstrip("!&=-~ ")
            v.ruby[i] = " " * ind + code
            v.parent(ind)
            v.stack.append((ind, "div", ""))   # children of ``= form_with … do`` keep their own wrapping
            cont = "ruby" if _code_continues(code) else ""
            continue
        if stripped.startswith("\\"):
            v.text(i, ind, stripped[1:])
            continue
        head = _HAML_HEAD.match(stripped)
        if not head.group(0) or stripped.startswith("#{"):
            v.text(i, ind, stripped)
            continue
        tag = (head.group(1) or "%div")[1:]
        cls = " ".join(p[1:] for p in re.findall(r"\.[\w-]+", head.group(2)))
        rest, attrs = stripped[head.end():], ""
        while rest[:1] in ("{", "(", "["):
            opener = rest[0]
            closer = {"{": "}", "(": ")", "[": "]"}[opener]
            end = _balanced(rest, 0, opener, closer)
            chunk = rest[:end]
            if opener == "{":
                attrs += _hash_attrs(chunk)
                if end == len(rest) and chunk.count("{") > chunk.count("}"):
                    cont, hash_depth = "hash", chunk.count("{") - chunk.count("}")
            elif opener == "(":
                attrs += _html_attrs(chunk)
            rest = rest[end:]
        rest = rest.lstrip("<>/&!")
        body = rest.strip()
        if body[:1] in ("=", "~"):
            code = body.lstrip("=~ ")
            v.element(i, ind, tag, cls, attrs, None, " " * ind + code)
            if _code_continues(code):
                cont = "ruby"
        else:
            v.element(i, ind, tag, cls, attrs, body, None)
    return "\n".join(v.markup), "\n".join(v.ruby)


_SLIM_HEAD = re.compile(r"([A-Za-z][\w:-]*)?((?:[.#][\w-]+)*)")
_SLIM_ATTR = re.compile(r"""(?<!\s)\s+([\w:@.-]+)\s*=\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|(?:\([^()]*\)|\[[^\[\]]*\]|[^\s"'])+)""")
_SLIM_FILTER = re.compile(r"(?<![a-z])([a-z]+):\s*$")


def _slim_tag(v: _Views, i: int, ind: int, stripped: str) -> str:
    """Emit one Slim tag line; returns ``"ruby"`` when its code continues on the next line."""
    head = _SLIM_HEAD.match(stripped)
    tag = head.group(1) or "div"
    cls = " ".join(p[1:] for p in re.findall(r"\.[\w-]+", head.group(2)))
    rest, attrs = stripped[head.end():], ""
    if rest[:1] in ("(", "[", "{"):
        closer = {"(": ")", "[": "]", "{": "}"}[rest[0]]
        end = _balanced(rest, 0, rest[0], closer)
        attrs += _html_attrs(rest[:end])
        rest = rest[end:]
    while True:
        m = _SLIM_ATTR.match(rest)
        if not m:
            break
        value = m.group(2)
        if value[:1] in "\"'":
            attrs += _attr(m.group(1), value[1:-1])
        rest = rest[m.end():]
    rest = rest.lstrip("<>")
    body = rest.strip()
    if body.startswith(":"):
        v.element(i, ind, tag, cls, attrs, "", None)
        inner = body[1:].strip()
        v.markup[i] = v.markup[i][: -len(f"</{tag}>")]
        sub = _Views(1)
        sub.stack = [(ind, tag, cls)]
        _slim_tag(sub, 0, ind + 1, inner)
        v.markup[i] += sub.markup[0] + f"</{tag}>"
        v.ruby[i] = sub.ruby[0]
        return ""
    if body.startswith("/"):
        body = body[1:].strip()
    if body[:1] == "=":
        code = body.lstrip("=<>' ")
        v.element(i, ind, tag, cls, attrs, None, " " * ind + code)
        return "ruby" if _code_continues(code) else ""
    v.element(i, ind, tag, cls, attrs, body, None)
    return ""


def slim_views(text: str) -> tuple[str, str]:
    """``(markup, ruby)`` views of a Slim file, same line count."""
    lines = text.split("\n")
    v = _Views(len(lines))
    block: tuple[int, str] | None = None
    cont = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        ind = _indent(line)
        if block and ind > block[0]:
            if block[1] == "ruby":
                v.ruby[i] = line
            elif block[1] == "text":
                v.text(i, block[2] if len(block) > 2 else block[0] + 1, stripped)
            continue
        block = None
        if cont == "ruby":
            v.ruby[i] = line
            cont = "ruby" if _code_continues(line) else ""
            continue
        if stripped.startswith("/") or stripped.startswith("doctype"):
            block = (ind, "hidden")
            continue
        f = _SLIM_FILTER.match(stripped)
        if f:
            name = f.group(1)
            block = (ind, "ruby" if name == "ruby" else "text" if name in _TEXT_FILTERS else "hidden")
            continue
        if stripped[0] in "|'":
            v.text(i, ind, stripped[1:])
            block = (ind, "text", ind)   # indented lines under a pipe are more of the same text
            continue
        if stripped.startswith("<"):
            v.markup[i] = line
            continue
        if stripped[0] in "=-":
            code = stripped.lstrip("=-<>' ")
            v.ruby[i] = " " * ind + code
            v.parent(ind)
            v.stack.append((ind, "div", ""))
            cont = "ruby" if _code_continues(code) else ""
            continue
        if not (stripped[0].isalpha() or stripped[0] in ".#"):
            v.text(i, ind, stripped)
            continue
        cont = _slim_tag(v, i, ind, stripped)
    return "\n".join(v.markup), "\n".join(v.ruby)


#: Option keys whose string value a person reads; every other ``key: "…"`` in view code is markup plumbing.
_VISIBLE_KEYS = frozenset({
    "title", "placeholder", "alt", "label", "confirm", "prompt", "include_blank", "disable_with", "hint", "text",
    "content", "notice", "alert", "message", "description", "summary", "aria_label", "aria-label", "caption",
})
_CODE_PAIR = re.compile(
    r"""(?:(?<![\w:])([A-Za-z_][\w-]*):\s*|:([A-Za-z_][\w-]*)\s*=>\s*|["']([\w:-]+)["']\s*=>\s*)"""
    r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')"""
)


def ruby_view_code(code: str) -> str:
    """Blank the string values of non-visible options (``class: "btn"``, ``method: :post``), same length."""
    def repl(m: re.Match) -> str:
        name = (m.group(1) or m.group(2) or m.group(3)).lower()
        if name in _VISIBLE_KEYS:
            return m.group()
        return m.group()[: m.start(4) - m.start()] + " " * len(m.group(4))

    return _CODE_PAIR.sub(repl, code)


def scan_indent_file(scanner, html_scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    """Scan a HAML or Slim file: the markup view with the HTML rules, the Ruby view with the Ruby literal pass."""
    from ..core.languages import language_for_suffix
    from .literals import scan_literal_lines

    views = slim_views if path.suffix.lower() == ".slim" else haml_views
    markup, ruby = views("\n".join(lines))
    rel = relative_posix(path, scanner.root)
    scan_markup_view(html_scanner, rel, markup, result)
    if ruby.strip():
        code = [ruby_view_code(line) for line in ruby.split("\n")]
        scan_literal_lines(scanner, language_for_suffix(".rb"), rel, code, result)
