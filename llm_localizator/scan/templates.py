"""Server-side template engines (ERB, EJS, Handlebars, Twig/Jinja/Liquid/Nunjucks, Go templates, Razor, FreeMarker, JSP).

All of them are HTML with embedded code. Per engine, comments and code tags are blanked, output expressions
become the slot word, and the remaining HTML goes through the same rules as ``.vue`` (``sfc.scan_markup_view``).
A template's text and attributes are what a person sees; its code is not.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ScanResult, relative_posix
from .views import MarkupView, blank, blank_match, scan_markup_view

__all__ = ["ENGINE_BY_SUFFIX", "template_markup", "scan_template_file", "scan_text_template"]

ENGINE_BY_SUFFIX = {
    ".erb": "erb", ".ejs": "erb", ".jsp": "erb", ".gsp": "erb",
    ".hbs": "mustache", ".handlebars": "mustache", ".mustache": "mustache",
    ".twig": "jinja", ".jinja": "jinja", ".jinja2": "jinja", ".j2": "jinja", ".njk": "jinja", ".liquid": "jinja",
    ".gohtml": "gotmpl", ".tmpl": "gotmpl", ".tpl": "gotmpl",
    ".cshtml": "razor", ".razor": "razor",
    ".ftl": "freemarker",
}

_S = re.S
_GO_CONTROL = re.compile(r"^\s*+-?\s*+(?:if|else|end|range|with|define|template|block|break|continue)\b")


def _sub(pattern: str, text: str, repl, flags: int = _S) -> str:
    return re.sub(pattern, repl, text, flags=flags)


_blank_m = blank_match
_slot_m = MarkupView.slot


def _erb(text: str) -> str:
    text = _sub(r"<%#.*?%>", text, _blank_m)           # comments
    text = _sub(r"<%--.*?--%>", text, _blank_m)        # JSP comments
    text = _sub(r"<%[=-]{1,2}.*?-?%>", text, _slot_m)  # output tags
    text = _sub(r"<%.*?-?%>", text, _blank_m)          # code tags
    return _sub(r"\$\{[^{}\n]*\}", text, _slot_m)      # JSP/EL


def _mustache(text: str) -> str:
    text = _sub(r"\{\{!--.*?--\}\}|\{\{!.*?\}\}", text, _blank_m)
    # Control tags (sections, partials, else) are code; ``{{name}}`` is output even at the end of a line (M2: an
    # end-of-line rule blanked it, so "Hello {{name}}" lost its slot).
    text = _sub(r"\{\{[#/^>][^{}]*\}\}|\{\{\s*else[^{}]*\}\}", text, _blank_m)
    return _sub(r"\{\{\{.{0,300}?\}\}\}|\{\{.{0,300}?\}\}", text, _slot_m)


def _jinja(text: str) -> str:
    # Spans are capped so a stray ``{{`` in prose (an ICU message, a math formula) cannot swallow the lines after it.
    text = _sub(r"\{#.{0,2000}?#\}", text, _blank_m)
    # Django ``{% blocktrans %}…{% endblocktrans %}`` (and ``blocktranslate``): the body is already translated.
    text = _sub(r"\{%-?\s*block(trans(?:late)?)\b.{0,4000}?\{%-?\s*endblock\1\s*-?%\}", text, _blank_m)
    text = _sub(r"\{%.{0,1000}?%\}", text, _blank_m)
    return _sub(r"\{\{.{0,300}?\}\}", text, _slot_m)


def _gotmpl(text: str) -> str:
    text = _sub(r"\{\{/\*.*?\*/\}\}", text, _blank_m)
    return _sub(r"\{\{(.*?)\}\}", text, lambda m: blank(m.group()) if _GO_CONTROL.match(m.group(1)) else _slot_m(m))


_RAZOR_CODE = re.compile(r"@\{|@(?:code|functions)\b")
_RAZOR_CONTROL = re.compile(r"@(?:if|foreach|for|while|switch|using|else)\b|\}\s*else\b")
_RAZOR_EXPR = re.compile(r"@\(.*?\)|@[A-Za-z_][\w.]*(?:\([^)\n]*\))?")
#: A C# statement on its own line inside a control block: ``var total = items.Count;``, ``count++;``.
_RAZOR_STATEMENT = re.compile(r"(?m)^[ \t]*+(?![<@])[^<\n]*[=(+-][^<\n]*;[ \t]*$")


def _brace_end(text: str, brace: int) -> int:
    """Index just past the ``}`` that closes the ``{`` at *brace* (end of text when unbalanced)."""
    depth = 0
    for j in range(brace, len(text)):
        depth += text[j] == "{"
        depth -= text[j] == "}"
        if depth == 0:
            return j + 1
    return len(text)


def _razor(text: str) -> str:
    """Code blocks (``@{ }``, ``@code``) are blanked; control blocks keep their markup body (M2: was O(n^2) and blanked
    every ``@if`` body, so the text people see inside conditionals was never scanned)."""
    text = _sub(r"@\*.*?\*@", text, _blank_m)
    text = _RAZOR_STATEMENT.sub(_blank_m, text)
    out, i, n = [], 0, len(text)
    closers: set[int] = set()
    while i < n:
        if text[i] == "@" and _RAZOR_CODE.match(text, i):
            brace = text.find("{", i)
            end = _brace_end(text, brace) if brace >= 0 else n
            out.append(blank(text[i:end]))
            i = end
            continue
        if text[i] in "@}" and _RAZOR_CONTROL.match(text, i):
            brace = text.find("{", i)
            if brace < 0 or "\n\n" in text[i:brace]:
                end = text.find("\n", i)
                end = n if end < 0 else end
                out.append(blank(text[i:end]))
                i = end
                continue
            closers.add(_brace_end(text, brace) - 1)
            out.append(blank(text[i:brace + 1]))
            i = brace + 1
            continue
        if i in closers:   # the ``}`` that closes a control block (``} else {`` was handled above)
            out.append(" ")
            i += 1
            continue
        if text[i] == "@" and not text.startswith("@@", i) and (m := _RAZOR_EXPR.match(text, i)):
            out.append(MarkupView.SLOT)
            i = m.end()
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _blade(text: str) -> str:
    text = _sub(r"\{\{--.*?--\}\}", text, _blank_m)
    text = _sub(r"@php\b.*?@endphp|<\?php.*?\?>", text, _blank_m)
    text = _sub(r"@(?:lang|trans|choice)\s*\([^)]*\)", text, _slot_m)        # already translated: nothing to say
    text = _sub(r"@(?:section|yield|extends|include|component|push|stack|props|slot)\s*\([^)]*\)", text, _blank_m)
    text = _sub(r"@[A-Za-z]+\s*(?:\((?:[^()]|\([^()]*\))*\))?", text, _blank_m)  # directives: @if (...), @endforeach
    return _sub(r"\{!!.*?!!\}|\{\{.*?\}\}", text, _slot_m)


def _freemarker(text: str) -> str:
    text = _sub(r"<#--.*?-->", text, _blank_m)
    text = _sub(r"</?[#@][^>]*>", text, _blank_m)
    return _sub(r"\$\{[^{}\n]*\}", text, _slot_m)


_ENGINES = {
    "blade": _blade, "erb": _erb, "mustache": _mustache, "jinja": _jinja, "gotmpl": _gotmpl, "razor": _razor, "freemarker": _freemarker,
}


def template_markup(text: str, engine: str) -> str:
    """Markup view with the same line numbers: engine code blanked, output expressions as the slot word."""
    return _ENGINES[engine](text)


def scan_template_file(raw_scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    engine = "blade" if path.name.lower().endswith(".blade.php") else ENGINE_BY_SUFFIX.get(path.suffix.lower())
    if engine is None:
        return
    rel = relative_posix(path, raw_scanner.root)
    text = "\n".join(lines)
    if _PLAIN_TEXT_TEMPLATE.search(path.name.lower()):
        _scan_plain_template(rel, template_markup(text, engine), result)
    else:
        scan_markup_view(raw_scanner, rel, template_markup(text, engine), result)
    if path.suffix.lower() == ".erb":
        _scan_erb_ruby(raw_scanner, rel, text, result)


_JINJA_TAG = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")


def scan_text_template(scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    """``templates/emails/report.txt``: a Jinja plain-text body (pool E: critiquebrainz). Needs a ``{{ }}``/``{% %}`` tag."""
    text = "\n".join(lines)
    if not _JINJA_TAG.search(text):
        return
    rel = relative_posix(path, scanner.root)
    _scan_plain_template(rel, template_markup(text, "jinja"), result)


#: ``mailer.text.erb``, ``digest.md.erb``, ``body.txt.twig``: the template renders plain text or Markdown, not HTML (B14).
_PLAIN_TEXT_TEMPLATE = re.compile(r"\.(?:text|txt|md|markdown)\.[a-z0-9]+$")


def _scan_plain_template(rel: str, view: str, result: ScanResult) -> None:
    """Plain-text and Markdown templates: each text line is judged like Markdown content, slots become ``{x}``."""
    from .content import _scan_markdown

    local = ScanResult()
    _scan_markdown(rel, view.split("\n"), local)
    # ``host: {{ host }}`` lines: a lowercase key and one slot is a machine-readable record (patchman report.txt), not
    # a sentence. A capitalised label (``Name: {{ name }}``) is still reported.
    result.hardcoded.extend(h for h in MarkupView.tidy(local.hardcoded) if not _KEY_SLOT.fullmatch(h.text.strip()))


_KEY_SLOT = re.compile(r"[a-z][a-z0-9_.-]{0,30}:\s*\{x\}")


_ERB_OUTPUT = re.compile(r"<%[=-]{1,2}(.*?)-?%>", re.S)


def _scan_erb_ruby(raw_scanner, rel: str, text: str, result: ScanResult) -> None:
    """``<%= link_to "Sign up", path %>``: the Ruby inside output tags goes through the Ruby literal pass."""
    from ..core.languages import language_for_suffix
    from .literals import scan_literal_lines
    from .markup_indent import ruby_view_code

    view = [" " if c != "\n" else "\n" for c in text]
    for m in _ERB_OUTPUT.finditer(text):
        view[m.start(1):m.end(1)] = text[m.start(1):m.end(1)]
    code = "".join(view)
    if code.strip():
        scan_literal_lines(raw_scanner, language_for_suffix(".rb"), rel,
                           [ruby_view_code(line) for line in code.split("\n")], result)
