"""Flutter ARB (Application Resource Bundle) catalog adapter.

ARB is JSON that is already ICU-native, so message values pass through
untouched -- the plural bridge is not needed here. What ARB adds is a metadata
convention: every resource ``foo`` may be accompanied by ``@foo``, an object
carrying ``description``, ``placeholders``, and similar.

That makes it the format where :meth:`load_entries` earns its place. The
``description`` is exactly a translator note, so a project using ARB needs no
sidecar ``context_dir`` at all -- the guidance is already in the file, and we
preserve it on write.

Keys beginning with ``@@`` are bundle-level attributes (``@@locale``,
``@@last_modified``); they are neither translatable nor per-key metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Catalog, FlatMessages, Message
from .io import atomic_write_text, load_json_object

__all__ = ["ArbCatalog"]


class ArbCatalog(Catalog):
    #: `@key.description` is a translator note carried by the file itself.
    carries_notes = True

    def __init__(self, root, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def _parse_json_dict(self, path: Path) -> dict:
        return load_json_object(path)

    def _raw(self, locale: str, namespace: str | None) -> dict:
        path = self.path_for(locale, namespace)
        if not path.exists():
            return {}
        return self._cached_load(path, self._parse_json_dict)

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        return {
            k: v for k, v in self._raw(locale, namespace).items()
            if isinstance(v, str) and not k.startswith("@")
        }

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        raw = self._raw(locale, namespace)
        out: dict[str, Message] = {}
        for key, value in raw.items():
            if key.startswith("@") or not isinstance(value, str):
                continue
            meta = raw.get(f"@{key}") or {}
            meta = meta if isinstance(meta, dict) else {}
            out[key] = Message(
                key=key,
                value=value,
                note=str(meta.get("description", "")),
                metadata={k: v for k, v in meta.items() if k != "description"},
            )
        return out

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)

        existing = self._raw(locale, namespace)
        # Metadata lives in the source bundle by convention; Flutter's tooling
        # only requires it there. Carry it into the target so descriptions are
        # not lost, and so a translator opening the file sees the guidance.
        source = self._raw(self.source_locale, namespace) if locale != self.source_locale else {}

        out: dict = {}
        for attr in ("@@locale", "@@last_modified", "@@context"):
            if attr in existing:
                out[attr] = existing[attr]
        out["@@locale"] = locale

        for key, value in messages.items():
            out[key] = value
            meta = existing.get(f"@{key}") or source.get(f"@{key}")
            if isinstance(meta, dict) and meta:
                out[f"@{key}"] = meta

        atomic_write_text(path, json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        self._bust_cache(path)
