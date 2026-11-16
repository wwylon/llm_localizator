"""CSV and a small TBX subset for glossary files. No catalogue keys."""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from pathlib import Path

from .xml_safe import xml_fromstring

__all__ = [
    "COLUMNS",
    "GlossaryRecord",
    "export_csv",
    "export_tbx",
    "parse_csv",
    "parse_tbx",
]

COLUMNS = ("term", "locale", "translation", "forbidden", "note")
# Written (and accepted) only when some term lists inflected forms; older files keep working.
FORMS_COLUMNS = COLUMNS + ("forms",)
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


class GlossaryRecord:
    """One term after a full parse. ``dnt`` is a row with no locale."""

    __slots__ = ("term", "dnt", "translations", "forbidden", "notes", "note", "forms")

    def __init__(self, term: str) -> None:
        self.term = term
        self.dnt = False
        self.translations: dict[str, str] = {}
        self.forbidden: dict[str, list[str]] = {}
        self.notes: dict[str, str] = {}
        self.note = ""
        self.forms: dict[str, list[str]] = {}


def export_csv(glossary: dict) -> str:
    """Write the merged glossary. An empty locale marks do-not-translate."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    with_forms = any(
        isinstance(data, dict) and any(str(key).endswith("_forms") and data[key] for key in data)
        for data in (glossary.get("terms") or {}).values()
    )
    writer.writerow(FORMS_COLUMNS if with_forms else COLUMNS)
    pad = [""] if with_forms else []
    for term in glossary.get("doNotTranslate") or []:
        if term:
            writer.writerow([term, "", "", "", ""] + pad)
    for term, data in (glossary.get("terms") or {}).items():
        if not term or not isinstance(data, dict):
            continue
        shared_note = str(data.get("note") or "")
        locales = [
            key for key in data
            if key != "note"
            and not str(key).endswith("_forbidden")
            and not str(key).endswith("_note")
            and not str(key).endswith("_forms")
        ]
        if not locales:
            writer.writerow([term, "", "", "", shared_note] + pad)
            continue
        for locale in locales:
            words = data.get(f"{locale}_forbidden") or []
            forbidden = ";".join(str(word) for word in words if word)
            note = str(data.get(f"{locale}_note") or shared_note or "")
            row = [term, locale, data.get(locale) or "", forbidden, note]
            if with_forms:
                row.append(";".join(str(f) for f in data.get(f"{locale}_forms") or [] if f))
            writer.writerow(row)
    return buffer.getvalue()


def parse_csv(text: str, *, path: str) -> list[GlossaryRecord]:
    """Parse every row first. A bad row names ``path`` and yields nothing."""
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not rows:
        raise ValueError(f"{path}: missing header")
    header = tuple(cell.strip() for cell in rows[0])
    if header not in (COLUMNS, FORMS_COLUMNS):
        raise ValueError(f"{path}: header must be {','.join(COLUMNS)}[,forms]")
    width = len(header)
    grouped: dict[str, GlossaryRecord] = {}
    order: list[str] = []
    for number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != width:
            raise ValueError(f"{path}: row {number}: expected {width} columns")
        term, locale, translation, forbidden, note, *rest = (cell.strip() for cell in row)
        forms = rest[0] if rest else ""
        if not term:
            raise ValueError(f"{path}: row {number}: term is empty")
        record = grouped.get(term)
        if record is None:
            record = GlossaryRecord(term)
            grouped[term] = record
            order.append(term)
        if not locale:
            if translation or forbidden:
                raise ValueError(f"{path}: row {number}: do-not-translate row has a translation")
            if record.translations or record.forbidden:
                raise ValueError(f"{path}: row {number}: {term!r} mixes a locale with do-not-translate")
            record.dnt = True
            if note:
                record.note = note
        else:
            if record.dnt:
                raise ValueError(f"{path}: row {number}: {term!r} mixes a locale with do-not-translate")
            record.translations[locale] = translation
            record.forbidden[locale] = [part.strip() for part in forbidden.split(";") if part.strip()]
            if forms:
                record.forms[locale] = [part.strip() for part in forms.split(";") if part.strip()]
            if note:
                record.notes[locale] = note
    return [grouped[term] for term in order]


def export_tbx(glossary: dict, *, source_locale: str) -> str:
    """Term and ``xml:lang`` only. A source-only entry is do-not-translate."""
    martif = ET.Element("martif", {"type": "TBX"})
    martif.set(XML_LANG, source_locale)
    body = ET.SubElement(ET.SubElement(martif, "text"), "body")
    for term in glossary.get("doNotTranslate") or []:
        if term:
            _lang_set(ET.SubElement(body, "termEntry"), source_locale, str(term))
    for term, data in (glossary.get("terms") or {}).items():
        if not term or not isinstance(data, dict):
            continue
        entry = ET.SubElement(body, "termEntry")
        _lang_set(entry, source_locale, str(term))
        for key, value in data.items():
            if (
                key in {"note"}
                or str(key).endswith("_forbidden")
                or str(key).endswith("_note")
                or str(key).endswith("_forms")
                or not value
            ):
                continue
            _lang_set(entry, str(key), str(value))
    ET.indent(martif)
    return ET.tostring(martif, encoding="unicode", xml_declaration=True)


def parse_tbx(text: str, *, path: str, source_locale: str) -> list[GlossaryRecord]:
    """Parse the whole document before the caller writes anything."""
    try:
        root = xml_fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    records: list[GlossaryRecord] = []
    for entry in root.iter("termEntry"):
        langs: dict[str, str] = {}
        for lang_set in entry.findall("langSet"):
            locale = lang_set.get(XML_LANG) or lang_set.get("lang") or ""
            term_node = lang_set.find("./tig/term")
            if term_node is None:
                term_node = lang_set.find(".//term")
            text_value = (term_node.text or "").strip() if term_node is not None else ""
            if locale and text_value:
                langs[locale] = text_value
        source = langs.get(source_locale) or ""
        if not source and langs:
            source = next(iter(langs.values()))
        if not source:
            raise ValueError(f"{path}: termEntry has no term")
        record = GlossaryRecord(source)
        targets = {locale: text for locale, text in langs.items() if locale != source_locale}
        if not targets:
            record.dnt = True
        else:
            record.translations = targets
        records.append(record)
    return records


def read_exchange(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _lang_set(entry: ET.Element, locale: str, term: str) -> None:
    lang = ET.SubElement(entry, "langSet")
    lang.set(XML_LANG, locale)
    ET.SubElement(ET.SubElement(lang, "tig"), "term").text = term
