"""Android ``strings.xml`` catalog adapter.

Android's plural model maps cleanly onto CLDR -- ``<item quantity="one">`` uses
the CLDR category names directly -- so the bridge here is mostly mechanical. The
awkward parts are Android's own escaping rules and its resource conventions.

* Apostrophes and double quotes must be backslash-escaped, and ``@`` or ``?`` at
  the start of a value would be read as a resource reference, so it is escaped.
* ``<string translatable="false">`` marks a resource that must never be
  translated; those are skipped on load, so they can never be sent to a model.
* Android positional arguments (``%1$s``) are preserved verbatim -- they are not
  ICU placeholders and must survive untouched.
* Plural ``<item>`` bodies use ``%d``; ICU uses ``#``. Converted both ways.

Locale directories follow Android's ``values-<qualifier>`` convention, where the
qualifier is not the BCP-47 tag: ``pt-BR`` is ``values-pt-rBR``. The template
handles the common case; :meth:`android_qualifier` does the transformation.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from ..core.plurals import ANDROID_QUANTITIES, PluralSet, build_icu_plural, parse_icu_plural
from .base import Catalog, FlatMessages, Message, warn_comments_lost
from .xml_safe import xml_parse
from .io import atomic_write_text

__all__ = ["AndroidXmlCatalog", "android_qualifier"]

_UNESCAPE_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|['\"@?\\nt])")
# Android resource names: a letter, then letters, digits, underscore, or dot.
_ANDROID_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
# A <string-array> item is the flat key ``name[index]``.
_ARRAY_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_.]*)\[(\d+)\]$")


def _check_android_name(key: str) -> None:
    """Refuse a name that would break the ``name="..."`` attribute."""
    if not (_ANDROID_NAME.fullmatch(key) or _ARRAY_KEY.fullmatch(key)):
        raise ValueError(
            f"Android resource name {key!r} must match {_ANDROID_NAME.pattern}"
        )


def android_qualifier(locale: str) -> str:
    """BCP-47 to Android resource qualifier: ``pt-BR`` -> ``pt-rBR``."""
    if "-" not in locale:
        return locale
    lang, region = locale.split("-", 1)
    return f"{lang}-r{region.upper()}"


def locale_from_qualifier(qualifier: str) -> str:
    """Inverse of :func:`android_qualifier`: ``pt-rBR`` -> ``pt-BR``."""
    m = re.fullmatch(r"([a-z]{2,3})-r([A-Z]{2})", qualifier)
    return f"{m.group(1)}-{m.group(2)}" if m else qualifier


def _unescape(text: str) -> str:
    def one(m: re.Match) -> str:
        tok = m.group(1)
        if tok == "n":
            return "\n"
        if tok == "t":
            return "\t"
        if len(tok) == 5 and tok[0] == "u":
            return chr(int(tok[1:], 16))
        return tok

    return _UNESCAPE_RE.sub(one, text)


def _escape(text: str) -> str:
    # Resource refs (@/?) must be checked on the raw value — quote/backslash
    # escaping can move a leading "@" off index 0 (e.g. "@it's").
    lead = "\\" if text[:1] in ("@", "?") else ""
    out = text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    out = out.replace("\n", "\\n")
    return xml_escape(lead + out, {})


_TOKEN_RE = re.compile(r"<!--(.*?)-->|<(/?)([A-Za-z][\w.-]*)([^>]*)>", re.DOTALL)
_NAME_RE = re.compile(r'\bname="([^"]+)"')
_EXACT_MARK = "llm-localizator-exact "
# Prefix/suffix text and variable/keyword around a plural (no <plurals> slot).
_ICU_MARK = "llm-localizator-icu "
_MARKS = (_EXACT_MARK, _ICU_MARK)


def _clean_comment(body: str) -> str:
    return " ".join(body.split())


def _notes_from_xml(text: str) -> dict[str, str]:
    """Map resource name to its comment note: comments directly above it, or
    on the same line after its closing tag. Multi-line comments are joined."""
    notes: dict[str, str] = {}
    pending: list[str] = []
    last_name: str | None = None
    pos = 0
    gap = ""  # text since the previous token
    for m in _TOKEN_RE.finditer(text):
        gap = text[pos:m.start()]
        pos = m.end()
        if m.group(0).startswith("<!--"):
            body = _clean_comment(m.group(1))
            if body.startswith(_MARKS):
                continue
            if last_name and "\n" not in gap and last_name not in notes and not pending:
                notes[last_name] = body  # trailing comment on the resource's line
                continue
            pending.append(body)
            continue
        closing, tag, attrs = m.group(2), m.group(3), m.group(4)
        if not closing and tag in ("string", "plurals"):
            nm = _NAME_RE.search(attrs)
            if nm and pending:
                notes[nm.group(1)] = "; ".join(p for p in pending if p)
            last_name = nm.group(1) if nm else None
        elif closing and tag in ("string", "plurals"):
            pass  # keep last_name so a trailing comment attaches to it
        else:
            last_name = None
        if not (closing and tag in ("string", "plurals")):
            pending = []
        elif pending:
            pending = []
    return notes


def _has_user_comments(text: str) -> bool:
    """Comments other than our own exact-branch markers (they are re-emitted)."""
    return any(
        not _clean_comment(m.group(1)).startswith(_MARKS)
        for m in re.finditer(r"<!--(.*?)-->", text, re.DOTALL)
    )


def _marker_comment(mark: str, data: dict) -> str:
    import json

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # A comment may not contain "--"; - is a valid JSON escape for "-".
    return "<!-- " + mark + payload.replace("-", "\\u002d") + " -->"


def _exact_branches_comment(branches: dict[str, str]) -> str:
    return _marker_comment(_EXACT_MARK, branches)


def _parse_icu_frame(node) -> dict[str, str]:
    import json

    for child in node:
        if child.tag is ET.Comment and isinstance(child.text, str):
            body = child.text.strip()
            if body.startswith(_ICU_MARK):
                try:
                    data = json.loads(body[len(_ICU_MARK):])
                except ValueError:
                    continue
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
    return {}


def _parse_exact_branches(node) -> dict[str, str]:
    import json

    out: dict[str, str] = {}
    for child in node:
        if child.tag is ET.Comment and isinstance(child.text, str):
            body = child.text.strip()
            if body.startswith(_EXACT_MARK):
                try:
                    data = json.loads(body[len(_EXACT_MARK):])
                except ValueError:
                    continue
                if isinstance(data, dict):
                    out.update({str(k): str(v).replace("%d", "#") for k, v in data.items()})
    return out


class AndroidXmlCatalog(Catalog):
    carries_notes = True  # <!-- comments --> immediately above a <string>

    locale_from_path = staticmethod(locale_from_qualifier)

    def __init__(self, root, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    def format_locale(self, locale: str) -> str:
        return android_qualifier(locale)

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    # ---- reading -----------------------------------------------------------

    def _parse_xml_root(self, path: Path):
        try:
            parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
            return xml_parse(path, parser=parser).getroot()
        except ET.ParseError as exc:
            raise ValueError(f"{path} is not valid XML: {exc}") from exc

    def _parse(self, locale: str, namespace: str | None):
        path = self.path_for(locale, namespace)
        if not path.exists():
            return None
        return self._cached_load(path, self._parse_xml_root)

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        root = self._parse(locale, namespace)
        if root is None:
            return {}

        out: FlatMessages = {}
        for node in root:
            name = node.get("name")
            if not name or node.get("translatable") == "false":
                continue
            if node.tag == "string":
                out[name] = _unescape("".join(node.itertext()))
            elif node.tag == "string-array":
                for i, item in enumerate(node.findall("item")):
                    out[f"{name}[{i}]"] = _unescape("".join(item.itertext()))
            elif node.tag == "plurals":
                branches = {
                    q: _unescape("".join(item.itertext())).replace("%d", "#")
                    for item in node.findall("item")
                    if (q := item.get("quantity")) in ANDROID_QUANTITIES
                }
                branches.update(_parse_exact_branches(node))  # `=0` etc., see save()
                if branches:
                    frame = _parse_icu_frame(node)
                    out[name] = build_icu_plural(PluralSet(
                        frame.get("v", "n"), branches,
                        prefix=frame.get("p", ""), suffix=frame.get("s", ""),
                        keyword=frame.get("k", "plural"),
                    ))
        return out

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        """Comments immediately preceding a resource (single or multi-line), or
        trailing it on the same line, are its translator note."""
        path = self.path_for(locale, namespace)
        values = self.load(locale, namespace)
        notes = _notes_from_xml(path.read_text(encoding="utf-8")) if path.exists() else {}
        return {
            k: Message(key=k, value=v, note=notes.get(k, ""))
            for k, v in values.items()
        }

    # ---- writing -----------------------------------------------------------

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        for key in messages:
            _check_android_name(key)
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        warn_comments_lost(path, "android-xml", _has_user_comments)

        # Carry `translatable="false"` resources through from the source file --
        # they belong in every locale but must never be translated.
        untranslatable: list[str] = []
        source_root = self._parse(self.source_locale, namespace)
        if source_root is not None:
            for node in source_root:
                if node.get("translatable") == "false":
                    untranslatable.append(ET.tostring(node, encoding="unicode").strip())

        lines = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
        lines += [f"    {frag}" for frag in untranslatable]

        arrays: dict[str, dict[int, str]] = {}
        for key, value in messages.items():
            am = _ARRAY_KEY.fullmatch(key)
            if am:
                arrays.setdefault(am.group(1), {})[int(am.group(2))] = value
                continue
            plural = parse_icu_plural(value)
            if plural is None:
                lines.append(f'    <string name="{key}">{_escape(value)}</string>')
                continue
            lines.append(f'    <plurals name="{key}">')
            frame = {
                k: v for k, v in (("p", plural.prefix), ("s", plural.suffix))
                if v
            }
            if plural.variable != "n":
                frame["v"] = plural.variable
            if plural.keyword != "plural":
                frame["k"] = plural.keyword
            if frame:
                lines.append("        " + _marker_comment(_ICU_MARK, frame))
            exact: dict[str, str] = {}
            for quantity, text in plural.branches.items():
                if quantity not in ANDROID_QUANTITIES:
                    # Android has no slot for `=0`; keep it in a marker comment
                    # so it survives a save/load cycle instead of being dropped.
                    exact[quantity] = text.replace("#", "%d")
                    continue
                body = _escape(text.replace("#", "%d"))
                lines.append(f'        <item quantity="{quantity}">{body}</item>')
            if exact:
                lines.append("        " + _exact_branches_comment(exact))
            lines.append("    </plurals>")

        for aname, items in arrays.items():
            lines.append(f'    <string-array name="{aname}">')
            for i in range(max(items) + 1):  # keep positions stable across gaps
                lines.append(f"        <item>{_escape(items.get(i, ''))}</item>")
            lines.append("    </string-array>")

        lines.append("</resources>")
        atomic_write_text(path, "\n".join(lines) + "\n")
        self._bust_cache(path)
