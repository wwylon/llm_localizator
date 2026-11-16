"""Apple ``.xcstrings`` string-catalog adapter (Xcode 15+).

One JSON file holds every locale::

    {"sourceLanguage": "en", "version": "1.0", "strings": {
       "Save": {"comment": "Button", "localizations": {
           "pl": {"stringUnit": {"state": "translated", "value": "Zapisz"}}}},
       "items": {"localizations": {"en": {"variations": {"plural": {
           "one": {"stringUnit": {"value": "%lld item"}},
           "other": {"stringUnit": {"value": "%lld items"}}}}}}}}}

Plural variations flatten to one ICU message ``{count, plural, one {...} other {...}}`` so the
engine's plural validation applies. A key with no source-language localization uses the key
itself as the source text, as Xcode does. Entries the engine cannot model (device or width
variations, substitutions, ``shouldTranslate: false``) are skipped on load and left untouched on
save, so writing a locale never damages them. Comments, ``extractionState`` and the state of
untouched values are preserved. ``comment`` becomes the translator note.

Path template: ``Localizable.xcstrings`` or ``{namespace}.xcstrings`` (no ``{locale}``).
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import FlatMessages, Message
from .io import atomic_write_text, read_json
from .ios_stringsdict import _find_plural_block, _split_branches
from .multilang_json import MultilangJsonCatalog

__all__ = ["XcstringsCatalog"]

_PLURAL_VAR = "count"


def _unit_value(unit: object) -> str | None:
    if isinstance(unit, dict) and isinstance(unit.get("stringUnit"), dict):
        value = unit["stringUnit"].get("value")
        return value if isinstance(value, str) else None
    return None


def _loc_to_text(loc: object) -> str | None:
    """The ICU text of one locale's localization, or None when it is not modelled."""
    if not isinstance(loc, dict):
        return None
    if set(loc) - {"stringUnit", "variations"}:
        return None
    if "variations" not in loc:
        return _unit_value(loc)
    variations = loc["variations"]
    if "stringUnit" in loc or not isinstance(variations, dict) or set(variations) != {"plural"}:
        return None
    plural = variations["plural"]
    if not isinstance(plural, dict) or not plural:
        return None
    branches = []
    for cat, unit in plural.items():
        text = _unit_value(unit)
        if text is None or set(unit) != {"stringUnit"}:
            return None
        branches.append(f"{cat} {{{text}}}")
    return f"{{{_PLURAL_VAR}, plural, {' '.join(branches)}}}"


def _text_to_loc(icu: str, old: dict | None) -> dict:
    """A localization for ``icu``, keeping the state of unchanged units from ``old``."""
    old_units = _units(old)

    def unit(path: str, text: str) -> dict:
        prev = old_units.get(path)
        if prev is not None and prev.get("value") == text:
            return {"stringUnit": dict(prev)}
        return {"stringUnit": {"state": "translated", "value": text}}

    block = _find_plural_block(icu)
    if block is None:
        return unit("", icu)
    start, end, _var, body = block
    prefix, suffix = icu[:start], icu[end:]
    branches = _split_branches(body)
    return {"variations": {"plural": {
        cat: unit(cat, f"{prefix}{text}{suffix}") for cat, text in branches.items()
    }}}


def _units(loc: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not isinstance(loc, dict):
        return out
    if isinstance(loc.get("stringUnit"), dict):
        out[""] = loc["stringUnit"]
    plural = (loc.get("variations") or {}).get("plural") if isinstance(loc.get("variations"), dict) else None
    if isinstance(plural, dict):
        for cat, node in plural.items():
            if isinstance(node, dict) and isinstance(node.get("stringUnit"), dict):
                out[cat] = node["stringUnit"]
    return out


class XcstringsCatalog(MultilangJsonCatalog):
    """Apple string catalogs: all locales in one JSON file."""

    carries_notes = True  # the per-key "comment"

    def __init__(self, root: Path, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    @staticmethod
    def _parse_raw(path: Path) -> dict:  # type: ignore[override]
        if not path.exists():
            return {}
        raw = read_json(path)
        if not isinstance(raw, dict) or not isinstance(raw.get("strings", {}), dict):
            raise ValueError(f"{path}: not an Apple string catalog")
        return raw

    def _entry_text(self, key: str, entry: object, locale: str) -> str | None:
        if not isinstance(entry, dict) or entry.get("shouldTranslate") is False:
            return None
        locs = entry.get("localizations")
        locs = locs if isinstance(locs, dict) else {}
        if locale in locs:
            return _loc_to_text(locs[locale])
        # Xcode treats the key as the source text when the source has no localization.
        return key if locale == self.source_locale else None

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        raw = self._load_raw(self.path_for(locale, namespace))
        out: FlatMessages = {}
        for key, entry in (raw.get("strings") or {}).items():
            text = self._entry_text(key, entry, locale)
            if text is not None:
                out[key] = text
        return out

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        raw = self._load_raw(self.path_for(locale, namespace))
        strings = raw.get("strings") or {}
        return {
            key: Message(key=key, value=value, note=str(strings[key].get("comment") or ""))
            for key, value in self.load(locale, namespace).items()
        }

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        # A corrupt file must raise: writing from {} would wipe every other locale.
        raw = self._parse_raw(path) if path.exists() else {}
        raw.setdefault("sourceLanguage", self.source_locale)
        raw.setdefault("version", "1.0")
        strings = raw.setdefault("strings", {})
        for key in list(strings):
            entry = strings[key]
            if key in messages or self._entry_text(key, entry, locale) is None:
                continue  # unmodelled entries are never touched
            locs = entry.get("localizations") if isinstance(entry.get("localizations"), dict) else {}
            locs.pop(locale, None)
            if locale == self.source_locale:
                del strings[key]
            elif locs:
                entry["localizations"] = locs
            else:
                entry.pop("localizations", None)
        for key, text in messages.items():
            entry = strings.setdefault(key, {})
            if entry.get("shouldTranslate") is False:
                continue
            locs = entry.setdefault("localizations", {})
            old = locs.get(locale)
            if old is None and locale == self.source_locale and text == key:
                if not locs:
                    del entry["localizations"]
                continue
            if old is not None and _loc_to_text(old) is None:
                continue  # an unmodelled shape stays as the translator left it
            if old is not None and _loc_to_text(old) == text:
                continue
            locs[locale] = _text_to_loc(text, old)
        raw["strings"] = dict(sorted(strings.items()))
        payload = json.dumps(raw, ensure_ascii=False, indent=2, separators=(",", " : "))
        atomic_write_text(path, payload + "\n")
        self._bust_cache(path)

    def locales_present(self) -> list[str]:
        found: set[str] = set()
        for ns in self.namespaces():
            path = self.path_for("", ns)
            if not path.exists():
                continue
            try:
                raw = self._load_raw(path)
            except (ValueError, OSError):
                continue
            for entry in (raw.get("strings") or {}).values():
                if isinstance(entry, dict) and isinstance(entry.get("localizations"), dict):
                    found.update(entry["localizations"])
        found.discard(self.source_locale)
        return sorted(found)
