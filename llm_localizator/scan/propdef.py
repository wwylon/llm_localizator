"""UI definition files made of property lines: QML, Kivy ``.kv`` and Godot ``.tscn`` / ``.tres`` (ADR-143).

Text is the quoted value of a text-bearing property: ``text: "Save"`` (QML, Kivy), ``text = "Save"`` (Godot).
A value that is not a plain quoted string is code or a translation call (``text: i18n("Save")``,
``text: root.title``) and is skipped. Godot string values may continue over several lines; embedded
``script/source`` blocks are code and never match because their quotes are escaped.
"""

from __future__ import annotations

import re

from .base import HardcodedString, ScanResult, relative_posix
from .prose import LabelWordMatcher, grade, is_lone_word, is_short_label
from .usage_calls import routed_re

__all__ = ["scan_propdef_file"]

_COMMON = (
    r"text|title|label|subtitle|description|tooltip|toolTip|placeholderText|displayName|statusText|headerText|"
    r"helperText|summary|prompt|hint|hint_text|info_text|helper_text|error_text|"
    r"ToolTip\.text|Accessible\.(?:name|description)"
)
_GODOT = (
    r"text|title|display_name|description|tooltip_text|hint_tooltip|placeholder_text|dialog_text|"
    r"ok_button_text|cancel_button_text|window_title|item_\d+/text|popup/item_\d+/text|name_text"
)
_QUOTED = r"""("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')(?=\s*(?:[,;}]|//|#|$))"""
_QML_KV = re.compile(rf"^\s*(?:readonly\s+property\s+\w+\s+\w+\s*:\s*)?(?:{_COMMON})\s*:\s*{_QUOTED}")
_QML_NESTED = re.compile(rf"""[{{,]\s*['"]?(?:{_COMMON})['"]?\s*:\s*{_QUOTED}""")
#: Built-in text properties, plus exported script properties named like text (``DISPLAY_NAME``, ``level_title``).
_GODOT_START = re.compile(
    # ``editor_description`` and other ``editor_*`` keys are notes for the Godot editor, never shown in the game (B13).
    rf"^(?!editor_)(?P<key>{_GODOT}|[A-Za-z_]*(?i:display_name|_title|_label|_caption|_subtitle|description|tooltip))\s*=\s*\"(?P<rest>.*)$"
)
_LABEL_WORD = LabelWordMatcher(3, 24)
_ESC = re.compile(r"\\(.)")
_NOT_TEXT = re.compile(r"^(?:res://|user://|uid://|https?://|#[0-9a-fA-F]{3,8}$|[\w./-]+\.(?:png|svg|tres|tscn|ogg|wav|ttf|gd)$)")


def _unquote(raw: str) -> str:
    body = raw[1:-1]
    body = _ESC.sub(lambda m: " " if m.group(1) in "nt" else m.group(1), body)
    return " ".join(body.split())


def _report(result: ScanResult, rel: str, line: int, text: str, where: str, judge: str | None = None) -> None:
    if not text or _NOT_TEXT.match(text) or not any(ch.isalpha() for ch in text):
        return
    judged = judge or text
    conf = grade(judged, "none", label=(_LABEL_WORD.match, is_lone_word, is_short_label))
    if conf is None:
        return
    result.hardcoded.append(HardcodedString(
        text, rel, line, reason=f"{where} property holds user-visible text; use a translation call or a catalogue key",
        confidence=conf,
    ))


#: Text-like names of a ``property string`` (``confirmText``, ``title``, ``emptyMessage``); not ``mode`` or ``font``.
_QML_PROP = re.compile(
    rf"^\s*(?:readonly\s+)?property\s+string\s+(?:\w*(?:[tT]ext|[tT]itle|[lL]abel|[dD]escription|[cC]aption|[hH]int|"
    rf"[mM]essage|[pP]laceholder|[hH]eading|[sS]ubtitle))\s*:\s*{_QUOTED}"
)
#: Choice lists a person reads: ``model: ["Fluid", "Image"]`` (ComboBox), ``nameFilters: ["Images (*.png)"]``.
_QML_LIST = re.compile(r"^\s*(?:model|nameFilters)\s*:\s*\[(?P<body>.*)\]\s*;?\s*$")
#: A text property whose quoted value continues on the next lines: ``text: '      QueMusic is…``.
_QML_OPEN = re.compile(rf"^\s*(?:{_COMMON})\s*:\s*(?P<q>['\"])(?P<rest>(?:(?!(?P=q)).)*)$")
#: Freedesktop entries: the untranslated ``Name=`` / ``Comment=`` keys (``Name[pl]=`` is already localized).
_DESKTOP_KEY = re.compile(r"^(?:Name|GenericName|Comment|Keywords|X-GNOME-FullName)=(?P<value>.+)$")


def _desktop(rel: str, lines: list[str], result: ScanResult) -> None:
    section = ""
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
            continue
        match = _DESKTOP_KEY.match(stripped)
        if match and section in ("", "[Desktop Entry]") or match and section.startswith("[Desktop Action"):
            value = match.group("value").strip()
            if stripped.startswith("Name=") and " " not in value:
                continue   # ``Name=QueMusic``: the product name
            judge = value.strip(";").replace(";", "; ") if stripped.startswith("Keywords=") else None
            _report(result, rel, number, value, "Desktop entry", judge=judge)


def _qml_list(result: ScanResult, rel: str, number: int, body: str) -> None:
    routed = _routed_spans(body)
    for lit in _EXPR_LIT.finditer(body):
        if any(a <= lit.start() < b for a, b in routed) or re.fullmatch(r"""["'][a-z][\w.-]*["']""", lit.group()):
            continue  # a translated entry, or an id (``"left"``, ``"en_US"``)
        _qml_literal(result, rel, number, lit.group())


def scan_propdef_file(scanner, path, lines: list[str], result: ScanResult) -> None:
    rel = relative_posix(path, scanner.root)
    suffix = path.suffix.lower()
    if suffix in {".tscn", ".tres"}:
        _godot(rel, lines, result)
        return
    if suffix == ".desktop":
        _desktop(rel, lines, result)
        return
    where = "QML" if suffix == ".qml" else "Kivy"
    in_block = False
    text_block = 0   # brace depth inside ``property string headline: { … }`` / ``text: { … }``
    open_quote = ""   # the quote of a text value spanning lines; its first line is reported, the rest is skipped
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if open_quote:
            if open_quote in line:
                open_quote = ""
            continue
        if where == "QML" and text_block:
            text_block += stripped.count("{") - stripped.count("}")
            ret = _QML_RETURN.search(stripped)
            if ret and not re.fullmatch(r"""["'][a-z][A-Za-z0-9_-]*["']""", ret.group(1)):  # ``return "busy"``: a state id
                _qml_literal(result, rel, number, ret.group(1))
            continue
        if where == "QML" and _QML_TEXT_BLOCK.match(line):
            text_block = stripped.count("{") - stripped.count("}")
            continue
        if in_block:
            in_block = "*/" not in stripped
            continue
        if stripped.startswith("/*") and "*/" not in stripped:
            in_block = True
            continue
        if stripped.startswith(("//", "#")):
            continue
        match = _QML_KV.match(line) or _QML_NESTED.search(line)
        if match:
            _report(result, rel, number, _unquote(match.group(match.lastindex)), where)
            continue
        if where != "QML":
            continue
        if prop := _QML_PROP.match(line):
            _qml_literal(result, rel, number, prop.group(1))
        elif listed := _QML_LIST.match(line):
            _qml_list(result, rel, number, listed.group("body"))
        elif opened := _QML_OPEN.match(line):
            open_quote = opened.group("q")
            _report(result, rel, number, " ".join(opened.group("rest").split()), where)
        else:
            _qml_expression(lines, number, result, rel)


def _godot(rel: str, lines: list[str], result: ScanResult) -> None:
    index = 0
    while index < len(lines):
        match = _GODOT_START.match(lines[index])
        index += 1
        if not match:
            continue
        start = index
        body = match.group("rest")
        while not re.search(r'(?<!\\)"\s*$', body) and index < len(lines):
            body += " " + lines[index].strip()
            index += 1
        body = re.sub(r'(?<!\\)"\s*$', "", body)
        _report(result, rel, start, _unquote('"' + body + '"'), "Godot")


#: A text property whose value is an expression: ``text: ok ? "Approved" : "Waiting"``, ``text: "TUNING " + n``.
_QML_EXPR_KEY = re.compile(rf"^\s*(?:[A-Z][\w.]*\s*\{{\s*)?(?:{_COMMON}|[a-z]\w*(?:Label|Title|Text|Hint|Message|Caption))\s*:\s*(?P<expr>.*?\S)\s*\}}?\s*$")
_EXPR_LIT = re.compile(r"""("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')""")
#: Before a literal: a comparison or a call that is not display (``raw === "ON"``, ``Qt.resolvedUrl("x")``).
_NOT_SHOWN_BEFORE = re.compile(r"(?:[=!]==?|[<>]=?|\b(?:qsTr|qsTranslate|qsTrId|i18n\w*|tr)\s*\(|(?<![\w.])[\w.]+\s*\()\s*$")
_CONTINUES = re.compile(r"(?:[?:+(]|&&|\|\|)\s*$")
_OPENS_NEXT = re.compile(r"^\s*(?:[?:+)]|&&|\|\|)")


def _qml_expression(lines: list[str], number: int, result: ScanResult, rel: str) -> None:
    """Literals inside a text-property expression, including its continuation lines."""
    m = _QML_EXPR_KEY.match(lines[number - 1])
    if not m or m.group("expr").startswith(("{", "function")):
        return
    parts = [(number, m.group("expr"))]
    depth = m.group("expr").count("(") - m.group("expr").count(")")
    i = number
    while i < len(lines) and len(parts) < 8 and (
        depth > 0 or _CONTINUES.search(parts[-1][1]) or _OPENS_NEXT.match(lines[i])
    ):
        nxt = lines[i].strip()
        if not nxt or nxt.startswith("//"):
            break
        parts.append((i + 1, nxt))
        depth += nxt.count("(") - nxt.count(")")
        i += 1
    if not any(_EXPR_LIT.search(text) for _, text in parts):
        return
    for lineno, text in parts:
        routed = _routed_spans(text)
        for lit in _EXPR_LIT.finditer(text):
            if _NOT_SHOWN_BEFORE.search(text[: lit.start()]) or any(a <= lit.start() < b for a, b in routed):
                continue
            _qml_literal(result, rel, lineno, lit.group())


#: Translation calls in QML: Qt's own, KDE ``i18n*``, and a project's helper object (``I18n.t("key", "FALLBACK")``,
#: ``Tr.tr(...)``): every literal in their argument list is already routed (B17).
_ROUTED_CALL = routed_re("qml_call")


#: Date/number formatting calls: their string arguments are patterns (``"dddd"``, ``"hh:mm"``), not text (B26).
_FORMAT_CALL = re.compile(r"\b(?:toLocale(?:Date|Time)?String|format(?:Date|Time|DateTime)|toString)\s*\(")


def _routed_spans(text: str) -> list[tuple[int, int]]:
    """Argument lists of translation calls: ``i18nc("@action", "Remove icon")`` is already routed."""
    spans = []
    for m in list(_ROUTED_CALL.finditer(text)) + list(_FORMAT_CALL.finditer(text)):
        depth, j = 0, m.end() - 1
        while j < len(text):
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            if depth == 0:
                break
            j += 1
        spans.append((m.start(), j + 1))
    return spans


#: ``property string headline: {`` or ``text: {``: a binding block whose ``return "…"`` values are shown.
_QML_TEXT_BLOCK = re.compile(
    rf"^\s*(?:(?:readonly\s+)?property\s+string\s+\w+|(?:{_COMMON}|[a-z]\w*(?:Label|Title|Text|Hint|Message|Caption)))\s*:\s*\{{\s*$"
)
#: ``return "Unknown"``, or the fallback of a returned expression: ``return name || "Unknown source"`` (``??``, ``:``).
_QML_RETURN = re.compile(
    r"""\breturn\s+(?:[^"'\n]*(?:\|\||\?\?|:)\s*)?("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')\s*;?\s*$"""
)
#: Pieces of markup, shell commands or paths glued into a binding: ``"<font color='"``, ``" -mindepth 1 | fzf"``.
_CODE_FRAGMENT = re.compile(r"[<>{}|`$]|(?:^|\s)--?[a-z]\w*|/\w[\w.-]*/|(?<!\w)\w+\(")
_ALL_CAPS = re.compile(r"^[A-Z][A-Z0-9'’ &/-]{1,59}$")


def _qml_literal(result: ScanResult, rel: str, lineno: int, raw: str) -> None:
    """Judge one quoted literal from a QML text binding; all-caps labels (``"TUNING"``, ``"NO LOCATION SET"``) count."""
    value = _unquote(raw)
    core = value.strip(" :;,.-()►▶•|/")
    if not core or _CODE_FRAGMENT.search(value):
        return
    if _ALL_CAPS.match(core) and any(ch.isalpha() for ch in core) and not re.fullmatch(r"[A-Z0-9_]+_[A-Z0-9_]+", core):
        result.hardcoded.append(HardcodedString(
            value, rel, lineno, confidence="medium",
            reason="QML text binding holds a label; use qsTr() or a catalogue key",
        ))
        return
    _report(result, rel, lineno, value, "QML", judge=core)

