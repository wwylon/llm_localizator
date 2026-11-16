"""String-literal hardcoded detection for languages without a framework scanner.

Extensions, comments, and quote style come from ``core.languages``. The prose
gate is the same one the JSX and HTML scanners use.

M3 split: the per-language lexers live in ``scan/lexers``, Apple catalogue routing in ``scan/apple_index`` and the
side-file facts in ``scan/project_index``. This module is the driver: one generic pass plus per-language hook tables
(``_FILE_HOOKS``, ``_SINK_HOOKS``, ``_ROUTE_HOOKS``) instead of an ``if lang.id ==`` chain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from ..core.languages import SourceLanguage, language_for_suffix, literal_languages
from .apple_index import SWIFTUI_KEYED, apple_routed
from .base import HardcodedString, ScanResult, paths_with_suffixes, relative_posix
from .ecosystems import ui_sink_before
from .lexers import iter_literals
from .literal_filters import blank_dev_blocks, clap_doc_comments, is_dev_context, log_lines
from .project_index import project_index
from .prose import LabelWordMatcher, dominant_script, grade, is_lone_word, is_prose, is_short_label
from .usage_calls import routed_re

__all__ = ["iter_literals", "scan_literal_file", "scan_literal_lines", "scan_unseen_literals"]
#: Translate calls and their quoted argument, from the one routed-call table (``usage_calls.ROUTED_TABLE``).
_ROUTED = routed_re("literal_call")
_ROUTED_ARG = routed_re("literal_arg")
_ROUTED_SUFFIX = routed_re("literal_suffix")


def _routed_for(scanner):
    """The routed-call patterns, extended with the project's own ``[scan] t_functions``."""
    names = tuple(getattr(scanner, "t_functions", ()) or ())
    if not names:
        return _ROUTED, _ROUTED_ARG
    return routed_re("literal_call", names), routed_re("literal_arg", names)
#: A statement that starts with a logging call: its text is for developers, not for people.
_LOG_START = re.compile(
    r"""^\s*(?:(?:logger|log|logging|_logger|_log|LOG|LOGGER|slog|Log|Timber|Debug|Trace|NSLog|os_log|debugPrint|error_log|Logger|Rails\.logger)\b[\w.]*\s*[(:]"""
    r"""|(?:log::|tracing::)?(?:info|debug|trace|warn|error)!\s*\("""
    r"""|q(?:Debug|Info|Warning|Critical)\s*\(\s*\)\s*<<|console\.\w+\s*\()"""
)
_UNESCAPE = re.compile(r"\\(.)")
_HTML_TEXT = re.compile(r">\s*([^<>{}\n]{2,}?)\s*<")
_MEMBER = re.compile(
    r"""(?:^|[\s{,(])([A-Za-z_]\w*)\s*[:=]\s*(["'])((?:\\.|(?!\2)[^\\\n])*)\2"""
)
_WORD_SPLIT = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def scan_unseen_literals(scanner, result: ScanResult, seen: set[Path]) -> None:
    """Scan literal-language files the active adapter did not already take."""
    for path in _literal_paths(scanner):
        if path in seen:   # both lists come from the same walk, so equal paths are equal objects (M4: no resolve())
            continue
        _consume(scanner, path, result)


def scan_literal_file(scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    lang = language_for_suffix(path.suffix)
    if lang is None or lang.detector != "literal":
        return
    scan_literal_lines(scanner, lang, relative_posix(path, scanner.root), lines, result)


#: PHP code regions: ``<?php … ?>``, ``<?= … ?>`` (to the end of file when unclosed).
_PHP_CODE = re.compile(r"<\?(?:php\b|=)?.*?(?:\?>|\Z)", re.S)


@dataclass
class _File:
    """One file of the literal pass, as the per-language hooks see it."""

    scanner: object
    lang: SourceLanguage
    rel: str
    lines: list[str]
    text: str
    result: ScanResult
    routed: re.Pattern[str]


#: The ``_SINK_HOOKS`` / ``_ROUTE_HOOKS`` answer for "already routed: report nothing".
_SKIP = object()


# ---------------------------------------------------------------- per-language hooks
def _typescript_whole_file(f: _File) -> None:
    """Same syntax as JS: judge each literal by its context, not a flat low."""
    from .js_context import context_pass

    context_pass(f.text, f.rel, f.result, first_hit=len(f.result.hardcoded))


def _php_markup(f: _File) -> None:
    """Only the HTML around ``<?php … ?>`` is markup (M2: PHP code lines went through the HTML check too)."""
    from .raw_js import RawJsScanner

    html_lines = _PHP_CODE.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), f.text).split("\n")
    for lineno, (line, html) in enumerate(zip(f.lines, html_lines), 1):
        if not html.strip() or f.routed.search(line):
            continue
        RawJsScanner._check_html_line(html, f.rel, lineno, f.result)


def _python_file(f: _File) -> set[tuple[int, str]]:
    """Server sinks from the AST pass; returns the ``(line, text)`` literals the generic pass must skip."""
    from .py_sinks import dev_strings, server_strings

    skip = dev_strings(f.text)
    _emit_python_sinks(server_strings(f.text), f.rel, f.result)
    skip |= {(h.line, h.text) for h in f.result.hardcoded if h.file == f.rel}  # sink hits: no low duplicate
    return skip


def _rust_file(f: _File) -> None:
    for doc_line, doc_text in clap_doc_comments(f.lines):
        f.result.hardcoded.append(HardcodedString(
            doc_text, f.rel, doc_line, reason="clap doc comment becomes --help text", confidence="medium",
        ))


def _go_file(f: _File) -> None:
    for lineno, line in enumerate(f.lines, 1):
        for tag in _GO_TAG.finditer(line):
            value = " ".join(tag.group(2).split())
            if is_prose(value) or (tag.group(1) != "default" and (is_lone_word(value) or is_short_label(value))):
                f.result.hardcoded.append(HardcodedString(
                    value, f.rel, lineno, reason=f"struct tag `{tag.group(1)}:` becomes CLI help or a default prompt",
                    confidence=grade(value),
                ))


def _go_sink(f: _File, line: str, literal: str, sink: str | None):
    if sink is not None or "%w" in literal:  # ``"read prefs: %w"`` wraps an internal error
        return sink
    if (_GO_ERR.search(line) and project_index(f.scanner).go_cli
            and re.search(r"[^\W\d_]{3,}", _GO_NOT_WORDS.sub(" ", literal))):  # a word left after verbs and paths
        return "fmt.Errorf"  # a CLI prints its errors to the person who ran it
    if is_prose(literal) and not _GO_ERR.search(line) and project_index(f.scanner).go_tui:
        return "terminal UI"  # a bubbletea/tview/termui app draws its prose on screen
    return None


def _swift_route(f: _File, line: str, literal: str, sink: str | None):
    if sink in SWIFTUI_KEYED and apple_routed(f.scanner, f.rel, literal):
        return _SKIP  # ``Text("Loading…")`` is a LocalizedStringKey and the catalogue translates it: already routed
    if sink in _SWIFT_NAMED_ARGS:
        return "print"  # ``title: "Github"``: a lone word may be a name; only prose counts there
    return sink


#: Replaces the literal pass for the whole file.
_WHOLE_FILE_HOOKS = {"typescript": _typescript_whole_file}
#: Runs on the raw text, before dev blocks are blanked.
_MARKUP_HOOKS = {"php": _php_markup}
#: Runs on the blanked text before the literal loop; may return ``(line, text)`` pairs the loop skips.
_FILE_HOOKS = {"python": _python_file, "rust": _rust_file, "go": _go_file}
#: Finds a sink the shared table missed (before the strings-file rule).
_SINK_HOOKS = {"go": _go_sink}
#: Decides a found sink is already routed (``_SKIP``) or weaker (after the strings-file rule).
_ROUTE_HOOKS = {"swift": _swift_route}
#: Languages whose developer text is judged by their own pass, not by ``_LOG_START`` / ``log_lines``.
_OWN_LOG_PASS = frozenset({"python"})
#: ``"#{…}"`` interpolation: a literal cut inside nested quotes is not a message.
_HASH_INTERP = frozenset({"ruby", "elixir"})


def scan_literal_lines(scanner, lang: SourceLanguage, rel: str, lines: list[str], result: ScanResult) -> None:
    """The literal pass over ``lines`` as language ``lang`` (also used for code views cut out of templates)."""
    routed_call, routed_arg_re = _routed_for(scanner)
    f = _File(scanner, lang, rel, lines, "\n".join(lines), result, routed_call)
    whole = _WHOLE_FILE_HOOKS.get(lang.id)
    if whole is not None:
        whole(f)
        return
    if (markup := _MARKUP_HOOKS.get(lang.id)) is not None:
        markup(f)
    members = _member_literals(lines) if lang.quotes == "script" else {}
    f.text = blank_dev_blocks(f.text, lang.id)  # previews and annotation arguments are never shown
    own_log = lang.id in _OWN_LOG_PASS
    logged = log_lines(lines) if not own_log else set()
    skip: set[tuple[int, str]] = set()
    if (file_hook := _FILE_HOOKS.get(lang.id)) is not None:
        skip = file_hook(f) or set()
    sink_hook, route_hook = _SINK_HOOKS.get(lang.id), _ROUTE_HOOKS.get(lang.id)
    strings_file = _STRINGS_FILE.fullmatch(Path(rel).stem.lower().replace("-", "_")) is not None
    for lineno, literal in iter_literals(f.text, lang):
        if skip and (lineno, " ".join(literal.split())) in skip:
            continue
        line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        # Only the literal handed to t(...) is routed; others on the line still count.
        routed_here = {
            _UNESCAPE.sub(r"\1", m.group(2) if m.group(2) is not None else m.group(4))
            for m in routed_arg_re.finditer(line)
        } | {_UNESCAPE.sub(r"\1", m.group(2)) for m in _ROUTED_SUFFIX.finditer(line)}
        if literal in routed_here:
            continue
        if not own_log and (_LOG_START.match(line) or lineno in logged):
            continue  # ``logger.info("…")``: developer text (Python is judged by its own AST pass)
        if lang.id in _HASH_INTERP and literal.count("#{") > literal.count("}"):
            continue  # cut inside an interpolation with nested quotes: ``"#{x ? "a" : "b"}"``, not a message
        if is_dev_context(line, literal):
            continue  # enum raw value, identifier constant, ``comment:`` argument
        if "</" in literal and len(literal) > 30 and not _only_inline_tags(literal) and hasattr(scanner, "_delegate"):
            _scan_embedded_markup(scanner, lang.id, rel, literal, lineno, result, lines)
            continue  # a page held in a string (Go raw-string templates, Java text blocks): judge it as markup
        if (lineno, literal) in members:
            result.hardcoded.append(HardcodedString(
                literal, rel, lineno, reason=members[(lineno, literal)], confidence="medium",
            ))
            continue
        sink = ui_sink_before(lang.id, line, literal)
        if sink_hook is not None:
            sink = sink_hook(f, line, literal, sink)
        if sink is None and strings_file and not line.lstrip().startswith(("import ", "package ", "#include", "using ")):
            sink = "strings file"  # ``strings.dart`` / ``Strings.kt``: the project's own home for UI text (B19)
        if route_hook is not None:
            sink = route_hook(f, line, literal, sink)
            if sink is _SKIP:
                continue
        _emit(literal, rel, lineno, result, sink=sink)


def _scan_embedded_markup(
    scanner, lang_id: str, rel: str, literal: str, lineno: int, result: ScanResult,
    source_lines: list[str] | None = None,
) -> None:
    """HTML inside a string literal: engine code blanked, then the same text/attribute rules as a template file."""
    from dataclasses import replace

    from .raw_js import RawJsScanner
    from .views import scan_markup_view
    from .templates import template_markup

    markup = template_markup(literal, "gotmpl" if lang_id == "go" else "jinja") if "{{" in literal else literal
    before = len(result.hardcoded)
    scan_markup_view(scanner._delegate(RawJsScanner), rel, markup, result)
    for i in range(before, len(result.hardcoded)):
        hit = result.hardcoded[i]
        line = hit.line + lineno - 1
        if source_lines is not None:
            # Triple-quoted strings and heredocs reach here with their whitespace collapsed, so every hit would sit
            # on the literal's first line (M2): find the text in the source from that line on.
            probe = hit.text[:40]
            for j in range(lineno - 1, min(len(source_lines), lineno - 1 + 400)):
                if probe and probe in " ".join(source_lines[j].split()):
                    line = j + 1
                    break
        result.hardcoded[i] = replace(hit, line=line)


_SINK_CONF = {"exception": "high", "flash": "high", "config-default": "medium", "return-tuple": "medium"}


def _emit_python_sinks(found, rel: str, result: ScanResult) -> None:
    """Strings the server puts in front of people (HTTPException detail, flash, UI config defaults)."""
    from .negatives import is_non_ui_literal

    for item in found:
        if is_non_ui_literal(item.text):
            continue
        conf = _SINK_CONF.get(item.sink, "medium")
        result.hardcoded.append(HardcodedString(
            item.text, rel, item.line,
            reason=f"server text ({item.sink}) reaches the screen; route through the catalogue",
            confidence=conf,
        ))


def _words(text: str) -> str:
    return " ".join(w.lower() for w in _WORD_SPLIT.findall(text))


def _member_literals(lines: list[str]) -> dict[tuple[int, str], str]:
    """``SAVE: "Save"`` / ``saveChanges = "Save changes"``: the member name is the text.

    Such a value is a label that stands in for a message key, which the prose gate misses
    when it is one word. Callers intersect with real (non-comment) literals.
    """
    found: dict[tuple[int, str], str] = {}
    for lineno, line in enumerate(lines, 1):
        for match in _MEMBER.finditer(line):
            name, _quote, value = match.groups()
            if len(value) < 2 or not any(ch.isalpha() for ch in value):
                continue
            if value == value.lower() and " " not in value and name.lower().replace("_", "") == value.replace("-", "").replace("_", ""):
                continue  # ``static const String base = 'base'``: a keyword, not a label
            if _words(name) and _words(name) == _words(value):
                found[(lineno, value)] = f"member '{name}' repeats its own label; use a message key"
    return found


_HTML_LEADING = re.compile(r"^([^<>{}\n]{2,})</[a-zA-Z]")   # greedy: callers strip the trailing space (M2)


def _emit(literal: str, rel: str, lineno: int, result: ScanResult, sink: str | None = None) -> None:
    from .negatives import is_non_ui_literal

    if "<" in literal and ">" in literal and _only_inline_tags(literal):
        # ``Click <b>here</b> to continue``: one message with inline formatting. Report it whole, as a catalogue would hold it.
        stripped = " ".join(_ANY_TAG.sub(" ", literal).split())
        if stripped and not is_non_ui_literal(stripped) and (is_prose(stripped) or (sink and is_lone_word(stripped))):
            result.hardcoded.append(HardcodedString(
                literal, rel, lineno, reason="message with inline markup; keep the tags in one catalogue entry",
                confidence="high" if sink else "medium",
            ))
        return
    if "<" in literal and ">" in literal:
        # HTML fragment chrome (SSR shells): medium so default reports show it.
        pieces: list[str] = [m.group(1).strip() for m in _HTML_TEXT.finditer(literal)]
        lead = _HTML_LEADING.match(literal.strip())
        if lead:
            pieces.append(lead.group(1).strip())
        for piece in pieces:
            if is_non_ui_literal(piece):
                continue
            if is_prose(piece) or (piece[:1].isupper() and " " in piece):
                result.hardcoded.append(HardcodedString(
                    piece, rel, lineno,
                    reason="HTML fragment chrome — route through catalogue",
                    confidence="medium",
                ))
        return
    if is_non_ui_literal(literal):
        return
    if sink in _STRONG_SINKS or (sink or "").startswith("JOptionPane."):
        if is_lone_word(literal) or is_short_label(literal):  # ``Toast.makeText(ctx, "nedelja", …)``: a lone lower-case word is still copy
            result.hardcoded.append(HardcodedString(
                literal, rel, lineno, reason=f"{sink}(…) shows this text to the user", confidence="medium",
            ))
            return
    label_ok = sink not in _PROSE_ONLY_SINKS and not (sink or "").startswith(('"', "'"))
    if sink and (is_prose(literal) or (label_ok and _LABEL_WORD.match(literal))):
        result.hardcoded.append(HardcodedString(
            literal, rel, lineno, reason=f"{sink}(…) shows this text to the user",
            confidence=grade(literal),
        ))
    elif is_prose(literal):
        # A bare literal is low: it may be a log line or an id. In alphabets that code and identifiers are never
        # written in (Cyrillic, Arabic, Hebrew, Greek, Thai, Devanagari) it is almost always copy (measured: 17 of 21).
        script_conf = "medium" if dominant_script(literal) in _COPY_SCRIPTS else "low"
        result.hardcoded.append(HardcodedString(
            literal, rel, lineno, confidence=script_conf,
            reason="text in a non-Latin script; route it through the catalogue" if script_conf == "medium" else "",
        ))


#: In a CLI project, what it prints is its UI: errors, ``fmt.Print*``/``Sprintf`` to the terminal, coloured text and the
#: project's own output helpers (``output.Error(…)``, ``ui.Info(…)``) (B3, B23). ``log.*`` stays developer text.
_GO_ERR = re.compile(
    r"\b(?:fmt\.Errorf|errors\.New|errors\.Errorf|errors\.Wrapf?|fmt\.Fprint(?:f|ln)?\(\s*(?:os\.Std(?:err|out)|w|out)|"
    r"fmt\.(?:Printf|Println|Print)\b|\)\.Sprint(?:f|ln)?\b|"
    r"(?:output|ui|out|printer|console|term|tui)\.(?:Error|Errorf|Info|Infof|Success|Successf|Warn|Warnf|Warning|Print|Printf|Println|Fatal)\b)"
)
#: Format verbs, URLs, paths and dotted identifiers: ``"github.com/x/cli v%s (%s/%s)"`` has no word a person reads.
_GO_NOT_WORDS = re.compile(r"%[-+# 0-9.*]*[a-zA-Z]|(?<!\S)\S*[/\\.]\S*|\bv\d")
#: Source files that are a project's own single home for UI text (not a catalogue): ``strings.dart``, ``Strings.kt``,
#: ``ui_texts.py``, ``messages.go``. Their label and prose literals are copy (B19).
_STRINGS_FILE = re.compile(r"(?:app_|ui_|user_)?(?:strings|texts|messages|labels|copy|copies|wording)(?:_\w+)?")
#: Go struct tags read by CLI libraries (kong, cobra-style, survey): ``help:"Show hidden files"``.
_GO_TAG = re.compile(r"""\b(help|default|group|placeholder|prompt|usage|description):"([^"\n]+)\"""")
_COPY_SCRIPTS = frozenset({"cyrillic", "arabic", "hebrew", "greek", "thai", "devanagari"})
#: Sinks that print anything (``echo "Bridge"``): a lone word there may be a name, so only prose counts.
_PROSE_ONLY_SINKS = frozenset({"echo", "print"})
#: Calls that only ever show text to a person.
_STRONG_SINKS = frozenset({"Toast.makeText", "Snackbar.make", "Text", "MessageBox.Show", "DisplayAlert", "QMessageBox::warning"})
_SWIFT_NAMED_ARGS = frozenset({
    "title", "message", "subtitle", "placeholder", "prompt", "description", "informativeText", "messageText",
    "buttonTitle", "buttonTitles", "headline", "detail", "summary",
})
#: One capitalised word handed to a UI sink is a label: ``setText("Save")``.
_LABEL_WORD = LabelWordMatcher(3, 24)


def _literal_paths(scanner):
    exts = [ext for lang in literal_languages() for ext in lang.extensions]
    yield from paths_with_suffixes(scanner, exts)


def _consume(scanner, path: Path, result: ScanResult) -> None:
    from .base import scan_file_hits

    scan_file_hits(scanner, path, result, partial(scan_literal_file, scanner))


_ANY_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
#: Page structure: a string holding these is a page fragment, not one sentence. Anything else (``<b>``, ``<link>``,
#: ``<sr>``, custom i18n tags) is inline markup inside one message.
_BLOCK_TAGS = frozenset({
    "div", "p", "ul", "ol", "li", "table", "tr", "td", "th", "thead", "tbody", "h1", "h2", "h3", "h4", "h5", "h6", "section",
    "article", "header", "footer", "nav", "main", "aside", "form", "input", "button", "select", "option", "textarea", "label",
    "html", "head", "body", "script", "style", "img", "svg", "iframe", "canvas", "video", "audio", "template", "fieldset",
})


def _only_inline_tags(literal: str) -> bool:
    """No page-structure tag: the string is one sentence with inline formatting."""
    tags = _ANY_TAG.findall(literal)
    return bool(tags) and all(re.match(r"</?([A-Za-z][A-Za-z0-9]*)", t).group(1).lower() not in _BLOCK_TAGS for t in tags)
