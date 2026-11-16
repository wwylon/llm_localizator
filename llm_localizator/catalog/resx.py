"""``.resx`` catalog adapter (.NET resource files).

A ``.resx`` file is XML: ``<resheader>`` boilerplate, an optional ``xsd:schema``,
then ``<data name=".."><value>..</value><comment>..</comment></data>`` entries.

* Only plain string entries are translatable. Entries carrying ``type`` or
  ``mimetype`` (images, binary blobs, file references) and designer metadata
  (names starting ``>>`` or ``$``) are skipped on load and kept verbatim on save.
* Saving splices into the existing file text instead of re-serialising it, so the
  resheaders, the schema and its namespace prefixes, typed entries and comments
  outside ``<data>`` survive byte for byte. Only the string entries change.
* A translator ``<comment>`` is the key's note and is kept when a value is rewritten.
* .NET composite placeholders (``{0}``, ``{1:N2}``) are left untouched.
* The culture code is in the file name (``Strings.de.resx``); BCP-47 tags are
  used as they are.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from .base import Catalog, FlatMessages, Message
from .io import atomic_write_text
from .xml_safe import xml_fromstring

__all__ = ["ResxCatalog"]

_DATA_RE = re.compile(r"[ \t]*<data\b[^>]*?(?:/>|>.*?</data>)[ \t]*\r?\n?", re.DOTALL)
_ROOT_CLOSE = re.compile(r"</root\s*>")
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<root>
  <resheader name="resmimetype">
    <value>text/microsoft-resx</value>
  </resheader>
  <resheader name="version">
    <value>2.0</value>
  </resheader>
  <resheader name="reader">
    <value>System.Resources.ResXResourceReader, System.Windows.Forms, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089</value>
  </resheader>
  <resheader name="writer">
    <value>System.Resources.ResXResourceWriter, System.Windows.Forms, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089</value>
  </resheader>
</root>
"""


def _is_string_entry(node) -> bool:
    name = node.get("name") or ""
    if node.get("type") or node.get("mimetype"):
        return False
    return bool(name) and not name.startswith((">>", "$"))


def _value(node) -> str:
    v = node.find("value")
    return "".join(v.itertext()) if v is not None else ""


def _comment(node) -> str:
    c = node.find("comment")
    return "".join(c.itertext()).strip() if c is not None else ""


def _render(name: str, value: str, comment: str) -> str:
    out = f'  <data name="{xml_escape(name, {chr(34): "&quot;"})}" xml:space="preserve">\n'
    out += f"    <value>{xml_escape(value)}</value>\n"
    if comment:
        out += f"    <comment>{xml_escape(comment)}</comment>\n"
    return out + "  </data>\n"


class ResxCatalog(Catalog):
    carries_notes = True  # <comment> inside <data>

    def __init__(self, root, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    # ---- reading -----------------------------------------------------------

    def _entries(self, path: Path) -> dict[str, Message]:
        try:
            tree = xml_fromstring(path.read_text(encoding="utf-8-sig"))
        except ET.ParseError as exc:
            raise ValueError(f"{path} is not valid XML: {exc}") from exc
        out: dict[str, Message] = {}
        for node in tree.findall("data"):
            if _is_string_entry(node):
                name = node.get("name")
                out[name] = Message(key=name, value=_value(node), note=_comment(node))
        return out

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        path = self.path_for(locale, namespace)
        return self._entries(path) if path.exists() else {}

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        path = self.path_for(locale, namespace)
        if not path.exists():
            return {}
        return self._cached_load(
            path, lambda p: {k: m.value for k, m in self._entries(p).items()}
        )

    # ---- writing -----------------------------------------------------------

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8-sig") if path.exists() else _HEADER
        pending = dict(messages)
        # Notes also live in the source file when the target has none yet.
        source_notes: dict[str, str] = {}
        src = self.path_for(self.source_locale, namespace)
        if locale != self.source_locale and src.exists():
            source_notes = {k: m.note for k, m in self._entries(src).items()}

        def swap(match: re.Match) -> str:
            frag = match.group(0)
            try:
                node = xml_fromstring(frag.strip())
            except ET.ParseError:
                return frag
            if not _is_string_entry(node):
                return frag  # typed entry, designer metadata: leave alone
            name = node.get("name")
            if name not in pending:
                return ""  # key no longer in the source: prune
            value = pending.pop(name)
            return _render(name, value, _comment(node) or source_notes.get(name, ""))

        text = _DATA_RE.sub(swap, text)
        if pending:
            close = _ROOT_CLOSE.search(text)
            if close is None:
                raise ValueError(f"{path} has no closing </root>")
            added = "".join(
                _render(k, v, source_notes.get(k, "")) for k, v in pending.items()
            )
            text = text[: close.start()] + added + text[close.start():]
        atomic_write_text(path, text)
        self._bust_cache(path)
