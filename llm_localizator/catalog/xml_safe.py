"""Shared XML parse helper — refuse entity expansion (XXE / billion laughs)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

__all__ = ["xml_fromstring", "xml_parse"]


def _parser() -> ET.XMLParser:
    try:
        return ET.XMLParser(resolve_entities=False)
    except TypeError:
        return ET.XMLParser()


def xml_fromstring(text: str):
    return ET.fromstring(text, parser=_parser())


def xml_parse(path, parser=None) -> ET.ElementTree:
    return ET.parse(path, parser=parser if parser is not None else _parser())
