"""XML UI definitions: Android layouts, XAML, Qt Designer ``.ui``, iOS ``.storyboard``/``.xib``.

Text lives in attributes (``android:text="Save"``, ``Content="Save"``, ``title="Save"``) or in ``<string>`` elements (Qt).
References to resources (``@string/save``, ``{Binding Name}``, ``{x:Static res:Strings.Save}``, ``?attr/x``) are already routed.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import HardcodedString, ScanResult, relative_posix
from .prose import LabelWordMatcher, grade

__all__ = ["is_xmlui_path", "scan_xmlui_file"]

_ANDROID_DIRS = ("/res/layout", "/res/menu", "/res/navigation", "/res/xml")
_ATTRS = (
    r"android:(?:text|hint|contentDescription|title|label|summary|subtitle|tooltipText|prompt|description)|"
    r"app:(?:title|subtitle|hint|helperText|errorText|label|contentDescription)|"
    r"(?:Content|Text|Header|ToolTip|Title|Label|PlaceholderText|Description|Caption|Watermark|Hint|HeaderText|"
    r"AutomationProperties\.Name|ToolTipService\.ToolTip)|"
    r"(?:title|text|placeholder|label|accessibilityLabel|subtitle|prompt|promptText|headerText|tooltipText)"
)
_ATTR = re.compile(rf"""(?<![\w:.-])(?:{_ATTRS})\s*=\s*(["'])(.*?)\1""", re.S)
_QT_STRING = re.compile(r"<string(?:\s[^>]*)?>([^<]+)</string>")
_QT_PROP = re.compile(r"""<property\s+name=["'](?:text|windowTitle|toolTip|title|placeholderText|statusTip|whatsThis)["']""")
_ELEMENT_TEXT = re.compile(r"<(\w+)\b[^<>]*>([^<>{}\n]{3,})<")
#: Resource elements whose text is a value, not copy: ``<SolidColorBrush>Black</SolidColorBrush>``.
_VALUE_ELEMENTS = re.compile(
    r"(?:Brush|Color|Thickness|CornerRadius|GridLength|Double|Int32|Boolean|Point|Rect|Size|Matrix|Geometry|"
    r"FontFamily|FontWeight|Style|Setter|Duration|KeyTime|Visibility)$", re.I)
_LABEL_WORD = LabelWordMatcher(3, 24)
_ENTITY = re.compile(r"&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def is_xmlui_path(path: Path) -> bool:
    low = "/" + path.as_posix().lower()
    if path.suffix.lower() == ".xml":
        return _is_appstream(path) or any(d in low for d in _ANDROID_DIRS)
    return path.suffix.lower() in {".xaml", ".ui", ".storyboard", ".xib", ".fxml"}


#: AppStream metadata (``org.example.App.metainfo.xml``, ``*.appdata.xml``): the text a software centre shows.
_APPSTREAM_TEXT = frozenset({"summary", "name", "p", "li", "caption", "developer_name"})


def _is_appstream(path: Path) -> bool:
    return path.name.lower().endswith((".metainfo.xml", ".appdata.xml"))


def _clean(value: str) -> str:
    value = _ENTITY.sub(lambda m: {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}.get(m.group(), m.group()), value)
    return " ".join(value.split())


def _routed(value: str) -> bool:
    v = value.strip()
    return not v or v[0] in "@?{$#%" or not any(ch.isalpha() for ch in v)


def _add(result: ScanResult, rel: str, line: int, text: str, reason: str) -> None:
    if _routed(text):
        return
    conf = grade(text, "none", label=(_LABEL_WORD.match,))
    if conf is None:
        return
    result.hardcoded.append(HardcodedString(text, rel, line, reason=reason, confidence=conf))


def scan_xmlui_file(scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    if not is_xmlui_path(path):
        return
    rel = relative_posix(path, scanner.root)
    text = "\n".join(lines)
    text = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
    for m in _ATTR.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        _add(result, rel, line, _clean(m.group(2)), "UI attribute in an XML layout, not a resource reference")
    if path.suffix.lower() == ".ui":
        for prop in _QT_PROP.finditer(text):
            m = _QT_STRING.search(text, prop.end(), prop.end() + 300)
            if m:
                _add(result, rel, text.count("\n", 0, m.start()) + 1, _clean(m.group(1)), "Qt Designer text property")
    elif _is_appstream(path):
        for m in _ELEMENT_TEXT.finditer(text):
            if m.group(1).lower() in _APPSTREAM_TEXT:
                _add(result, rel, text.count("\n", 0, m.start(2)) + 1, _clean(m.group(2)), "AppStream store text")
    elif path.suffix.lower() in {".xaml"}:
        for m in _ELEMENT_TEXT.finditer(text):
            if _VALUE_ELEMENTS.search(m.group(1)):
                continue
            _add(result, rel, text.count("\n", 0, m.start(2)) + 1, _clean(m.group(2)), "XAML element text")
