"""Qt Linguist ``.ts`` catalogue adapter: one file per locale (ADR-140).

A ``.ts`` file groups ``<message>`` elements in ``<context>`` blocks. Qt identifies a message by
(context, source text, disambiguation comment), so the flat key is ``context<EOT>source`` and, when a
disambiguation ``<comment>`` exists, ``context<EOT>source<EOT>comment`` (EOT is gettext's own separator).
A message in the default context (no ``<name>``) has the bare source text as its key.

* The source-locale file may leave ``<translation>`` empty (Qt projects keep English in ``<source>``);
  its value is then the source text. A target value is the ``<translation>`` text; unfinished and
  vanished/obsolete messages with no text are skipped when loading.
* ``numerus="yes"`` messages (``%n``) are ICU plurals: ``<numerusform>`` slots map to CLDR categories in
  gettext order (``gettext_slot_order``); ``%n`` is written as ``#`` and back.
* Saving splices into the existing text, so ``<location>``, comments, ``<extracomment>`` and the header
  survive byte for byte; a changed translation loses ``type="unfinished"``. A message removed from the
  source is pruned; vanished and obsolete ones are kept.

Path template: ``translations/app_{locale}.ts`` (``de-DE`` is written ``de_DE``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from ..core.plurals import (
    PluralSet, build_icu_plural, fill_catchall_categories, gettext_slot_order, parse_icu_plural,
)
from .base import Catalog, FlatMessages, Message
from .io import atomic_write_text
from .xml_safe import xml_fromstring

__all__ = ["QtTsCatalog"]

SEP = "\x04"
_CONTEXT = re.compile(r"[ \t]*<context\b[^>]*>.*?</context>[ \t]*\r?\n?", re.DOTALL)
_MESSAGE = re.compile(r"[ \t]*<message\b[^>]*?(?:/>|>.*?</message>)[ \t]*\r?\n?", re.DOTALL)
_TRANSLATION = re.compile(r"<translation\b([^>]*?)(?:/>|>.*?</translation>)", re.DOTALL)
_TYPE_ATTR = re.compile(r"\s+type\s*=\s*(\"[^\"]*\"|'[^']*')")
_DEAD = {"vanished", "obsolete"}


def _key(context: str, source: str, comment: str) -> str:
    if not context and not comment:
        return source
    return SEP.join([context, source] + ([comment] if comment else []))


def _split(key: str) -> tuple[str, str, str]:
    parts = key.split(SEP)
    if len(parts) == 1:
        return "", parts[0], ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], SEP.join(parts[2:])


def _text(el) -> str:
    return "".join(el.itertext()) if el is not None else ""


def _identity(context: str, msg) -> str:
    return _key(context, _text(msg.find("source")), _text(msg.find("comment")))


def _translation_value(msg, locale: str, is_source: bool) -> str | None:
    """The ICU value of one message, or None when it has no text to offer."""
    tr = msg.find("translation")
    source = _text(msg.find("source"))
    numerus = msg.get("numerus") == "yes"
    ttype = tr.get("type") if tr is not None else None
    if ttype in _DEAD:
        return None
    if numerus:
        forms = [_text(f) for f in tr.findall("numerusform")] if tr is not None else []
        if not any(forms):
            if not is_source:
                return None
            forms = [source, source]
        order = gettext_slot_order(locale, len(forms))
        branches = {order[i]: f.replace("%n", "#") for i, f in enumerate(forms) if i < len(order) and f}
        return build_icu_plural(PluralSet("n", fill_catchall_categories(branches, locale))) if branches else None
    value = _text(tr)
    if value:
        return value
    return source if is_source else None


def _header(source: str, target: str | None) -> str:
    lang = f' language="{(target or source).replace("-", "_")}"'
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n'
            f'<TS version="2.1"{lang} sourcelanguage="{source.replace("-", "_")}">\n</TS>\n')


class QtTsCatalog(Catalog):
    carries_notes = True  # <extracomment>

    def __init__(self, root, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def format_locale(self, locale: str) -> str:
        return locale.replace("-", "_")

    @staticmethod
    def locale_from_path(fragment: str) -> str:
        return fragment.replace("_", "-")

    # ---- reading -----------------------------------------------------------

    def _entries(self, path: Path, locale: str) -> dict[str, Message]:
        raw = path.read_text(encoding="utf-8-sig")
        try:
            tree = xml_fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError(f"{path} is not valid Qt Linguist XML: {exc}") from exc
        is_source = locale == self.source_locale
        out: dict[str, Message] = {}
        for ctx in tree.findall("context"):
            name = _text(ctx.find("name"))
            for msg in ctx.findall("message"):
                value = _translation_value(msg, locale, is_source)
                if value is None:
                    continue
                key = _identity(name, msg)
                out[key] = Message(key=key, value=value, note=_text(msg.find("extracomment")).strip())
        return out

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        path = self.path_for(locale, namespace)
        return self._entries(path, locale) if path.exists() else {}

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        path = self.path_for(locale, namespace)
        if not path.exists():
            return {}
        return self._cached_load(path, lambda p: {k: m.value for k, m in self._entries(p, locale).items()})

    # ---- writing -----------------------------------------------------------

    def _translation_xml(self, locale: str, value: str, numerus: bool, nforms: int, indent: str) -> str:
        plural = parse_icu_plural(value) if numerus else None
        if plural is not None:
            order = gettext_slot_order(locale, nforms or None)
            forms = "".join(
                f"\n{indent}    <numerusform>{xml_escape(t.replace('#', '%n'))}</numerusform>"
                for t in plural.ordered(order)
            )
            return f"<translation>{forms}\n{indent}</translation>"
        return f"<translation>{xml_escape(value)}</translation>"

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        is_source = locale == self.source_locale
        if path.exists():
            text = path.read_text(encoding="utf-8-sig")
            try:
                xml_fromstring(text)
            except ET.ParseError as exc:  # never rewrite a file we cannot read
                raise ValueError(f"{path} is not valid Qt Linguist XML: {exc}") from exc
        else:
            text = _header(self.source_locale, None if is_source else locale)
        pending = dict(messages)
        nl = "\r\n" if "\r\n" in text else "\n"

        def swap_message(context: str):
            def swap(match: re.Match) -> str:
                frag = match.group(0)
                try:
                    node = xml_fromstring(frag.strip())
                except ET.ParseError:
                    return frag
                tr = node.find("translation")
                if tr is not None and tr.get("type") in _DEAD:
                    return frag
                key = _identity(context, node)
                if key not in pending:
                    return ""  # no longer in the source: prune
                value = pending.pop(key)
                numerus = node.get("numerus") == "yes" or parse_icu_plural(value) is not None
                current = _translation_value(node, locale, is_source)
                if current == value:
                    return frag
                nforms = len(tr.findall("numerusform")) if tr is not None else 0
                indent = (re.match(r"[ \t]*", frag).group(0)) + "    "
                new_tr = self._translation_xml(locale, value, numerus, nforms, indent)
                if numerus and node.get("numerus") != "yes":
                    frag = re.sub(r"<message\b", '<message numerus="yes"', frag, count=1)
                found = _TRANSLATION.search(frag)
                if found:
                    return frag[: found.start()] + new_tr + frag[found.end():]
                close = frag.rfind("</message>")
                return frag[:close] + f"{indent}{new_tr}{nl}" + frag[close:] if close > 0 else frag
            return swap

        def swap_context(match: re.Match) -> str:
            block = match.group(0)
            name_match = re.search(r"<name>(.*?)</name>", block, re.DOTALL)
            name = _text(xml_fromstring(f"<n>{name_match.group(1)}</n>")) if name_match else ""
            return _MESSAGE.sub(swap_message(name), block)

        text = _CONTEXT.sub(swap_context, text)
        if pending:
            by_ctx: dict[str, list[tuple[str, str, str]]] = {}
            for key, value in pending.items():
                ctx, source, comment = _split(key)
                by_ctx.setdefault(ctx, []).append((source, comment, value))
            for ctx, items in by_ctx.items():
                body = ""
                for source, comment, value in items:
                    numerus = parse_icu_plural(value) is not None
                    attr = ' numerus="yes"' if numerus else ""
                    com = f"        <comment>{xml_escape(comment)}</comment>\n" if comment else ""
                    tr = self._translation_xml(locale, value, numerus, 0, "        ")
                    body += (f"    <message{attr}>\n        <source>{xml_escape(source)}</source>\n{com}"
                             f"        {tr}\n    </message>\n")
                existing = re.search(
                    rf"(<context>\s*<name>{re.escape(xml_escape(ctx))}</name>.*?)(</context>)", text, re.DOTALL)
                if existing:
                    text = text[: existing.start(2)] + body.replace("\n", nl) + text[existing.start(2):]
                else:
                    block = f"<context>\n    <name>{xml_escape(ctx)}</name>\n{body}</context>\n"
                    close = text.rfind("</TS>")
                    if close < 0:
                        raise ValueError(f"{path} has no closing </TS>")
                    text = text[:close] + block.replace("\n", nl) + text[close:]
        atomic_write_text(path, text)
        self._bust_cache(path)
