"""Flat-JSON catalog adapter.

One JSON object per (locale, namespace) with no nesting -- the i18next default,
and the shape most hand-rolled catalogues use. Keys containing dots are treated
as opaque strings rather than paths, which is the difference from
``json-nested``: ``{"a.b": "x"}`` stays one key here and becomes ``{"a":{"b":…}}``
there.

For a single-file project, omit ``{namespace}`` from the path template:

    path = "locales/{locale}.json"
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Catalog, FlatMessages
from .io import atomic_write_text, load_json_object

__all__ = ["JsonFlatCatalog"]


class JsonFlatCatalog(Catalog):
    def __init__(self, root, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        return self._cached_load(self.path_for(locale, namespace), self._parse)

    @staticmethod
    def _parse(path: Path) -> FlatMessages:
        raw = load_json_object(path)
        return {k: v for k, v in raw.items() if isinstance(v, str)}

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(messages, ensure_ascii=False, indent=2)
        atomic_write_text(path, payload + "\n")
        self._bust_cache(path)
