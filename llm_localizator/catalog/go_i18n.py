"""go-i18n catalog adapter.

Reads and writes JSON files in the go-i18n v2 format:

    [
      {"id": "UserGreeting", "translation": "Hello {{.Name}}!"},
      {"id": "ItemCount",    "translation": {"one": "One item.", "other": "{{.Count}} items."}}
    ]

ICU plural forms are used for round-trips through llm_localizator; the
``translation`` field may be either a plain string (no plurals) or an object
keyed by CLDR plural category (``zero``, ``one``, ``two``, ``few``, ``many``,
``other``).  On load, plural objects are serialised as a JSON string so the
pipeline can handle them opaquely; on save they are restored.

Typical path template:

    path = "locales/{locale}.json"

The ``{namespace}`` token is optional; go-i18n projects commonly use a single
file per locale with no namespace concept.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Catalog, FlatMessages
from .io import atomic_write_text
from .io import read_json

__all__ = ["GoI18nCatalog"]

_PLURAL_KEYS = frozenset({"zero", "one", "two", "few", "many", "other"})


def _load_translation(t) -> str:
    if isinstance(t, str):
        return t
    if isinstance(t, dict):
        return json.dumps(t, ensure_ascii=False, sort_keys=True)
    return str(t)


def _save_translation(val: str):
    # If it looks like a JSON object with plural keys, restore it
    if val.startswith("{"):
        try:
            d = json.loads(val)
            if isinstance(d, dict) and any(k in _PLURAL_KEYS for k in d):
                return d
        except json.JSONDecodeError:
            pass
    return val


def _entry_text(entry: dict) -> str | None:
    """Catalogue value of one entry: ``translation``, else top-level plural forms."""
    if entry.get("translation") is not None:
        return _load_translation(entry["translation"])
    forms = {k: v for k, v in entry.items() if k in _PLURAL_KEYS and isinstance(v, str)}
    if not forms:
        return None
    if set(forms) == {"other"}:
        return forms["other"]
    return _load_translation(forms)


def _read_raw(path: Path) -> list[dict]:
    """Existing entries (id -> raw dict, file order); ``[]`` if unreadable."""
    try:
        raw = read_json(path)
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict) and isinstance(e.get("id"), str)]


def _merge_entry(old: dict | None, key: str, value: str) -> dict:
    """Entry for ``key``; keeps every unmodelled field of ``old``."""
    if old is None:
        return {"id": key, "translation": _save_translation(value)}
    if _entry_text(old) == value:
        return old  # unchanged: byte-for-byte identical
    entry = dict(old)
    new = _save_translation(value)
    if "translation" in entry or not any(k in _PLURAL_KEYS for k in entry):
        entry["translation"] = new
        return entry
    # Top-level plural form: rewrite plural fields in place of the old ones.
    forms = new if isinstance(new, dict) else {"other": new}
    out: dict = {}
    placed = False
    for k, v in entry.items():
        if k in _PLURAL_KEYS:
            if not placed:
                out.update(forms)
                placed = True
            continue
        out[k] = v
    return out


class GoI18nCatalog(Catalog):
    """go-i18n v2 JSON message files (array of {id, translation} objects).

    Per-entry fields the pipeline does not model (``description``, ``hash``,
    ...) and entry order are preserved across ``save``.
    """

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        return self._cached_load(self.path_for(locale, namespace), self._parse)

    @staticmethod
    def _parse(path: Path) -> FlatMessages:
        if not path.exists():
            return {}
        try:
            raw = read_json(path)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, list):
            raise ValueError(f"{path}: go-i18n format must be a JSON array")
        out: FlatMessages = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            msg_id = entry.get("id")
            text = _entry_text(entry)
            if isinstance(msg_id, str) and text is not None:
                out[msg_id] = text
        return out

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        old = {e["id"]: e for e in _read_raw(path)}
        # Existing keys keep file order; new keys follow, sorted.
        order = [k for k in old if k in messages]
        order += sorted(k for k in messages if k not in old)
        entries = [_merge_entry(old.get(k), k, messages[k]) for k in order]
        payload = json.dumps(entries, ensure_ascii=False, indent=2)
        atomic_write_text(path, payload + "\n")
        self._bust_cache(path)
