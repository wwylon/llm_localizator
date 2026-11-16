"""XLIFF 1.2 / 2.0 catalogue adapter: one ``.xlf`` file per locale (C-044, ADR-97).

Each file holds one ``<file>`` of translation units. The source-locale file carries the
text in ``<source>``; a target-locale file carries it in ``<target>`` beside a copy of the
source. The version is detected per file; new files are written as XLIFF 1.2.

* Saving splices into the existing text, like ``resx``: the header, ``<file>`` attributes,
  notes, ``approved``/``state`` attributes, inline markup of unchanged values and units
  the engine does not model (``translate="no"``) survive byte for byte.
* A changed target gets ``state="translated"``; an unchanged one is not rewritten.
* ``<note>`` text is the key's note. Inline markup (``<g>``, ``<x/>``, ``<ph>``) is flattened
  to its text when a unit is read; a value rewritten by the engine is plain text.
* A unit removed from the source is pruned from target files.

Path template: ``i18n/{namespace}.{locale}.xlf`` (or without ``{namespace}``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from .base import Catalog, FlatMessages, Message
from .io import atomic_write_text
from .xml_safe import xml_fromstring

__all__ = ["XliffCatalog"]

_UNIT_V1 = re.compile(r"[ \t]*<trans-unit\b[^>]*?(?:/>|>.*?</trans-unit>)[ \t]*\r?\n?", re.DOTALL)
_UNIT_V2 = re.compile(r"[ \t]*<unit\b[^>]*?(?:/>|>.*?</unit>)[ \t]*\r?\n?", re.DOTALL)
_VERSION = re.compile(r"<xliff\b[^>]*\bversion\s*=\s*[\"']([^\"']+)[\"']")
_TARGET = re.compile(r"<target\b([^>]*?)(?:/>|>.*?</target>)", re.DOTALL)
_SOURCE_END = re.compile(r"</source>")
_SEG_OPEN = re.compile(r"<segment\b([^>]*)>")
_STATE_ATTR = re.compile(r"\s+state\s*=\s*(\"[^\"]*\"|'[^']*')")


def _is_v2(text: str) -> bool:
    match = _VERSION.search(text)
    return bool(match) and match.group(1).strip().startswith("2")


def _text(el) -> str:
    return "".join(el.itertext()) if el is not None else ""


def _notes(unit) -> str:
    parts = []
    for note in [*unit.findall("{*}note"), *unit.findall("{*}notes/{*}note")]:
        text = "".join(note.itertext()).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _field(unit, v2: bool, name: str) -> str:
    if v2:
        return "".join(_text(seg.find(f"{{*}}{name}")) for seg in unit.findall("{*}segment"))
    return _text(unit.find(f"{{*}}{name}"))


def _modelled(unit) -> bool:
    return bool(unit.get("id")) and unit.get("translate") != "no"


def _header(source: str, target: str | None, name: str) -> str:
    attrs = f"original={quoteattr(name)} source-language={quoteattr(source)}"
    if target:
        attrs += f" target-language={quoteattr(target)}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
        f'  <file {attrs} datatype="plaintext">\n    <body>\n    </body>\n  </file>\n</xliff>\n'
    )


def _render(uid: str, source: str, target: str | None, note: str, v2: bool) -> str:
    note_xml = ""
    if note:
        note_xml = (
            f"      <notes><note>{xml_escape(note)}</note></notes>\n" if v2
            else f"        <note>{xml_escape(note)}</note>\n"
        )
    tgt = "" if target is None else f"<target>{xml_escape(target)}</target>"
    if v2:
        seg = f"        <source>{xml_escape(source)}</source>\n"
        if tgt:
            seg += f"        {tgt}\n"
        return (
            f"    <unit id={quoteattr(uid)}>\n{note_xml}      <segment>\n{seg}      </segment>\n    </unit>\n"
        )
    out = f"      <trans-unit id={quoteattr(uid)}>\n{note_xml}"
    out += f"        <source>{xml_escape(source)}</source>\n"
    if tgt:
        out += f"        {tgt}\n"
    return out + "      </trans-unit>\n"


def _set_text(fragment: str, v2: bool, field: str, value: str) -> str:
    """Replace the text of ``<source>`` or ``<target>`` in one unit fragment."""
    esc = xml_escape(value)
    if field == "source":
        return re.sub(r"(<source\b[^>]*>).*?(</source>)", lambda m: m.group(1) + esc + m.group(2),
                      fragment, count=1, flags=re.DOTALL)
    found = _TARGET.search(fragment)
    if found:
        attrs = _STATE_ATTR.sub("", found.group(1)).rstrip()
        state = "" if v2 else ' state="translated"'
        return fragment[: found.start()] + f"<target{attrs}{state}>{esc}</target>" + fragment[found.end():]
    end = _SOURCE_END.search(fragment)
    if end is None:
        return fragment
    state = "" if v2 else ' state="translated"'
    nl = "\r\n" if "\r\n" in fragment else "\n"
    indent = re.search(r"([ \t]*)<source\b", fragment)
    pad = indent.group(1) if indent else "        "
    return fragment[: end.end()] + f"{nl}{pad}<target{state}>{esc}</target>" + fragment[end.end():]


def _mark_v2_state(fragment: str) -> str:
    def swap(match: re.Match) -> str:
        attrs = _STATE_ATTR.sub("", match.group(1))
        return f'<segment{attrs} state="translated">'
    return _SEG_OPEN.sub(swap, fragment, count=1)


class XliffCatalog(Catalog):
    carries_notes = True  # <note>

    def __init__(self, root, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    # ---- reading -----------------------------------------------------------

    def _entries(self, path: Path, locale: str) -> dict[str, Message]:
        raw = path.read_text(encoding="utf-8-sig")
        try:
            tree = xml_fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError(f"{path} is not valid XLIFF: {exc}") from exc
        v2 = _is_v2(raw)
        field = "source" if locale == self.source_locale else "target"
        out: dict[str, Message] = {}
        for unit in tree.findall(".//{*}unit" if v2 else ".//{*}trans-unit"):
            if not _modelled(unit):
                continue
            uid = unit.get("id")
            out[uid] = Message(key=uid, value=_field(unit, v2, field), note=_notes(unit))
        return out

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        path = self.path_for(locale, namespace)
        return self._entries(path, locale) if path.exists() else {}

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        path = self.path_for(locale, namespace)
        if not path.exists():
            return {}
        return self._cached_load(
            path, lambda p: {k: m.value for k, m in self._entries(p, locale).items()}
        )

    # ---- writing -----------------------------------------------------------

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        is_source = locale == self.source_locale
        sources: dict[str, Message] = {}
        if not is_source:
            src = self.path_for(self.source_locale, namespace)
            if src.exists():
                sources = self._entries(src, self.source_locale)
        if path.exists():
            text = path.read_text(encoding="utf-8-sig")
            try:
                xml_fromstring(text)
            except ET.ParseError as exc:  # never rewrite a file we cannot read
                raise ValueError(f"{path} is not valid XLIFF: {exc}") from exc
        else:
            text = _header(self.source_locale, None if is_source else locale,
                           namespace or path.stem)
        v2 = _is_v2(text)
        field = "source" if is_source else "target"
        pending = dict(messages)
        unit_re = _UNIT_V2 if v2 else _UNIT_V1

        def swap(match: re.Match) -> str:
            frag = match.group(0)
            try:
                node = xml_fromstring(frag.strip())
            except ET.ParseError:
                return frag
            if not _modelled(node):
                return frag  # translate="no" or no id: leave alone
            uid = node.get("id")
            if uid not in pending:
                return ""  # key no longer in the source: prune
            value = pending.pop(uid)
            if _field(node, v2, field) == value:
                return frag
            frag = _set_text(frag, v2, field, value)
            if v2 and not is_source:
                frag = _mark_v2_state(frag)
            return frag

        text = unit_re.sub(swap, text)
        if pending:
            close = re.search(r"[ \t]*</(?:body|file)>", text) if not v2 else re.search(r"[ \t]*</file>", text)
            if close is None:
                raise ValueError(f"{path} has no closing </body>")
            added = ""
            for uid, value in pending.items():
                src = sources.get(uid)
                if is_source:
                    added += _render(uid, value, None, "", v2)
                else:
                    added += _render(uid, src.value if src else "", value, src.note if src else "", v2)
            nl = "\r\n" if "\r\n" in text else "\n"
            if nl != "\n":
                added = added.replace("\n", nl)
            text = text[: close.start()] + added + text[close.start():]
        atomic_write_text(path, text)
        self._bust_cache(path)
