"""TMX 1.4 read and write. Catalogue keys are not stored."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .tm import TMEntry, TranslationMemory
from .xml_safe import xml_fromstring

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

__all__ = ["export_tmx", "parse_tmx"]


def _prop(parent: ET.Element, name: str, value: str) -> None:
    node = ET.SubElement(parent, "prop", {"type": name})
    node.text = value


def export_tmx(tm: TranslationMemory, locale: str, source_locale: str) -> str:
    """Every JSONL line for one locale, including superseded rows."""
    ET.register_namespace("xml", "http://www.w3.org/XML/1998/namespace")
    root = ET.Element("tmx", {"version": "1.4"})
    ET.SubElement(root, "header", {
        "srclang": source_locale or "en",
        "adminlang": "en",
        "datatype": "plaintext",
    })
    body = ET.SubElement(root, "body")
    for entry, _superseded in tm.rows(locale):
        tu = ET.SubElement(body, "tu")
        if entry.quality_score is not None:
            _prop(tu, "x-quality", str(entry.quality_score))
        _prop(tu, "x-verified", "true" if entry.verified else "false")
        if entry.model:
            _prop(tu, "x-model", entry.model)
        if entry.provider:
            _prop(tu, "x-provider", entry.provider)
        _tuv(tu, source_locale or "en", entry.source)
        _tuv(tu, locale, entry.text)
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def _tuv(parent: ET.Element, lang: str, text: str) -> None:
    tuv = ET.SubElement(parent, "tuv")
    tuv.set(XML_LANG, lang)
    seg = ET.SubElement(tuv, "seg")
    seg.text = text or ""


def parse_tmx(xml_text: str, locale: str) -> list[dict]:
    """Target-locale units. Each dict has source, text, and optional props."""
    try:
        root = xml_fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"invalid TMX: {exc}") from exc
    header = root.find("header")
    source_locale = (header.get("srclang") if header is not None else None) or "en"
    body = root.find("body")
    if body is None:
        return []
    units: list[dict] = []
    for tu in body.findall("tu"):
        props = {
            (prop.get("type") or ""): (prop.text or "")
            for prop in tu.findall("prop")
        }
        texts: dict[str, str] = {}
        for tuv in tu.findall("tuv"):
            lang = tuv.get(XML_LANG) or tuv.get("lang") or ""
            seg = tuv.find("seg")
            texts[lang] = "" if seg is None or seg.text is None else seg.text
        target = texts.get(locale)
        source = texts.get(source_locale, "")
        if target is None or not source:
            continue
        score = props.get("x-quality")
        try:
            quality = float(score) if score not in (None, "") else None
        except ValueError:
            quality = None
        units.append({
            "source": source,
            "text": target,
            "quality_score": quality,
            "verified": props.get("x-verified", "").lower() in {"1", "true", "yes"},
            "model": props.get("x-model") or "import",
            "provider": props.get("x-provider") or "import",
        })
    return units


def score_of(entry: TMEntry | None) -> float:
    if entry is None or entry.quality_score is None:
        return 0.0
    return float(entry.quality_score)
