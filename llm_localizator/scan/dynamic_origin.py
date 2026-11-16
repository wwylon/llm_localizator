"""Where crawl "dynamic" text comes from: API copy, API data, or repeated rows (B1, ADR-133).

The QA crawl calls visible Latin text that is not a source literal "dynamic". Most of
it is data (task names, paper titles, ids), which must never be localized. The crawl
records the JSON responses each page loads; this module matches leftovers against
them and against repetition in the page.

Origins:

* ``api-copy`` — equal to a JSON value under a message-like field (``detail``,
  ``error``, ``message`` …): English the server writes for people. Actionable.
* ``api-data`` — equal to any other JSON value: content. Not actionable.
* ``repeated`` — one selector pattern shows five or more distinct values: a list or
  table of records. Not actionable.
* ``value`` — no word left once numbers, units, ids and acronyms are removed
  ("GPU 5.4G", "71 MB", "2m53s"). Not actionable.
* ``unknown`` — none of the above: runtime-assembled text. Actionable.

Pure: data in, data out.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

__all__ = ["COPY_FIELDS", "json_strings", "selector_pattern", "classify_dynamic", "ACTIONABLE", "is_value_text"]

#: JSON field names whose string values are messages for people, not content.
COPY_FIELDS = frozenset({
    "detail", "error", "errors", "message", "msg", "hint", "warning", "warnings",
    "reason", "status_text", "statustext", "notice", "tip", "help", "description_ui",
})
ACTIONABLE = frozenset({"api-copy", "unknown"})
_REPEAT_MIN = 5
_VALUE_TOKEN = re.compile(
    r"^(?:[\d.,:/%+-]+[a-zA-Z]{0,3}|[A-Z]{1,5}|[KMGTP]i?B|[a-zA-Z]{0,3}[\d.,:/%+-]+|[^\W\d_]*[\d_]\w*|[^\w\s]+)$")
_NTH = re.compile(r":nth-(?:child|of-type)\(\d+\)|\[\d+\]|#[\w-]*\d[\w-]*")


def json_strings(obj, endpoint: str, *, _field: str = "", _out=None) -> dict[str, tuple[str, str]]:
    """``{text: (endpoint, field)}`` for every string in a JSON value (first hit wins)."""
    out = {} if _out is None else _out
    if isinstance(obj, dict):
        for key, value in obj.items():
            json_strings(value, endpoint, _field=str(key), _out=out)
    elif isinstance(obj, list):
        for value in obj:
            json_strings(value, endpoint, _field=_field, _out=out)
    elif isinstance(obj, str):
        text = " ".join(obj.split())
        if text and text not in out:
            out[text] = (endpoint, _field)
    return out


def selector_pattern(selector: str | None) -> str:
    """The selector with row indices and numbered ids removed (rows of one list match)."""
    return _NTH.sub("", selector or "")


def is_value_text(text: str) -> bool:
    """Only numbers, units, ids, acronyms and symbols: a measurement, not copy."""
    tokens = text.split()
    return bool(tokens) and all(_VALUE_TOKEN.match(t) for t in tokens)


def classify_dynamic(items: Iterable[dict], responses: dict[str, tuple[str, str]]) -> list[dict]:
    """Copy of ``items`` with ``origin`` (and ``producer`` for API text) set."""
    items = [dict(i) for i in items]
    by_pattern: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in items:
        by_pattern[(item.get("page") or "", selector_pattern(item.get("selector")))].add(item["text"])
    for item in items:
        text = " ".join((item.get("text") or "").split())
        hit = responses.get(text)
        if hit:
            endpoint, field = hit
            item["origin"] = "api-copy" if field.casefold() in COPY_FIELDS else "api-data"
            item["producer"] = f"api:{endpoint}#{field}" if field else f"api:{endpoint}"
            continue
        pattern = (item.get("page") or "", selector_pattern(item.get("selector")))
        if pattern[1] and len(by_pattern[pattern]) >= _REPEAT_MIN:
            item["origin"] = "repeated"
            continue
        item["origin"] = "value" if is_value_text(text) else "unknown"
    return items
