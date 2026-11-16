"""Multi-language single-file JSON catalog adapter.

Handles glossary-style files where all locales live in one JSON file:

    {
      "terms": {
        "trick":    { "pl": "lewa", "ar": "خدعة" },
        "declarer": { "pl": "rozgrywający" }
      },
      "doNotTranslate": ["Stayman", "Blackwood"]
    }

Top-level keys whose values are lists (e.g. ``doNotTranslate``) are skipped.
Top-level keys whose values are dicts are term tables; each term key maps to
a dict of ``locale -> translation``.

Path template should omit ``{locale}`` since locale is stored inline:

    path = "messages/{namespace}.json"
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Catalog, FlatMessages
from .io import atomic_write_text, load_json_object

__all__ = ["MultilangJsonCatalog"]

_LOCALE_RE_STR = r"^[a-z]{2,3}([_-][A-Za-z0-9]{2,8})?$"

import re
from .io import read_json
_LOCALE_RE = re.compile(_LOCALE_RE_STR)


def _is_locale(key: str) -> bool:
    return bool(_LOCALE_RE.match(key))


def _extract_all_terms(raw: dict) -> dict[str, dict[str, str]]:
    """Extract a flat ``{term: {locale: value}}`` map from a raw JSON dict.

    Handles two shapes:

    * **Flat**: ``{"trick": {"pl": "lewa"}}`` — top-level keys are terms.
    * **Sectioned**: ``{"terms": {"trick": {"pl": "lewa"}}}`` — top-level keys
      are section names whose values are the term table.

    The sectioned shape is detected when a top-level value is a dict whose own
    values are *also* dicts (i.e., it is one level deeper than a plain term
    table).  List values (e.g. ``doNotTranslate``) are always skipped.
    """
    result: dict[str, dict[str, str]] = {}
    for top_key, top_val in raw.items():
        if not isinstance(top_val, dict):
            continue
        # Decide: is top_val a term table {"term": {locale: val}}
        # or a flat entry {"locale": "value"}?
        inner_are_dicts = any(isinstance(v, dict) for v in top_val.values())
        if inner_are_dicts:
            # Sectioned: top_val is a term table
            for term, locales in top_val.items():
                if isinstance(locales, dict):
                    for locale, translation in locales.items():
                        if isinstance(translation, str):
                            result.setdefault(term, {})[locale] = translation
        else:
            # Flat: top_key is the term
            for locale, translation in top_val.items():
                if isinstance(translation, str):
                    result.setdefault(top_key, {})[locale] = translation
    return result


class MultilangJsonCatalog(Catalog):
    """All locales in one JSON file; terms/locale values stored inline.

    Namespace maps to the filename (``{namespace}.json``).  The ``{locale}``
    token must be absent from the path template.
    """

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    # ---- path helpers -------------------------------------------------------

    def path_for(self, locale: str, namespace: str | None = None) -> Path:
        # locale is stored inline; produce a locale-free path
        template = self.path_template.replace("{locale}/", "").replace("{locale}", "")
        if namespace is not None and "{namespace}" in template:
            template = template.replace("{namespace}", namespace)
        return self.root / template

    def discover_namespaces(self) -> list[str]:  # type: ignore[override]
        template = self.path_template.replace("{locale}/", "").replace("{locale}", "")
        if "{namespace}" not in template:
            return [""]
        prefix, _, suffix = template.partition("{namespace}")
        base = (self.root / prefix).resolve()
        if not base.is_dir():
            return []
        results = []
        for p in sorted(base.iterdir()):
            if p.name.startswith("."):
                continue
            if p.is_file() and suffix and p.name.endswith(suffix.lstrip("/")):
                stem = p.stem
                results.append(stem)
        return results

    # ---- raw cache (path-keyed, locale-independent) -------------------------

    def _load_raw(self, path: Path) -> dict[str, dict[str, str]]:
        """Return the full term→locale→value map, using the mtime cache."""
        return self._cached_load(path, self._parse_raw)  # type: ignore[return-value]

    @staticmethod
    def _parse_raw(path: Path) -> dict:  # type: ignore[return-value]
        if not path.exists():
            return {}
        return _extract_all_terms(load_json_object(path))

    # ---- load ---------------------------------------------------------------

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        path = self.path_for(locale, namespace)
        all_terms = self._load_raw(path)
        return {term: locales[locale]
                for term, locales in all_terms.items()
                if locale in locales}

    # ---- save ---------------------------------------------------------------

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        # Read the whole file so we preserve other locales' data
        if path.exists():
            # Unreadable/corrupt file must raise: writing from {} would wipe
            # every other locale's data in this shared file.
            raw: dict = read_json(path)
        else:
            raw = {}
        # Find the first dict-of-dicts section to write into, or create "terms"
        target_section: dict | None = None
        for top_key, top_val in raw.items():
            if isinstance(top_val, dict) and any(isinstance(v, dict) for v in top_val.values()):
                target_section = top_val
                break
        if target_section is None:
            # Flat structure or empty file: write directly at top level
            target_section = raw
        keep = set(messages)
        for term in list(target_section):
            entry = target_section.get(term)
            if term not in keep and isinstance(entry, dict):
                # Remove only this locale's value; preserve other locales' data.
                entry.pop(locale, None)
                if not entry:
                    del target_section[term]
        for term, translation in messages.items():
            entry = target_section.setdefault(term, {})
            if isinstance(entry, dict):
                entry[locale] = translation
        payload = json.dumps(raw, ensure_ascii=False, indent=2)
        atomic_write_text(path, payload + "\n")
        self._bust_cache(path)

    # ---- locales_present ----------------------------------------------------

    def locales_present(self) -> list[str]:
        """Scan all term-table files to find which locales appear.

        Uses the same flat/sectioned extraction as ``load`` so sectioned files
        ``{"terms": {"trick": {"pl": "…"}}}`` report ``pl``, not ``trick``.
        """
        found: set[str] = set()
        for ns in self.namespaces():
            path = self.path_for("", ns)
            if not path.exists():
                continue
            try:
                terms = self._load_raw(path)
            except (json.JSONDecodeError, OSError, ValueError):
                continue
            for locales in terms.values():
                for key in locales:
                    if _is_locale(key) and key != self.source_locale:
                        found.add(key)
        return sorted(found)
