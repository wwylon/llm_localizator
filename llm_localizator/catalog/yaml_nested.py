"""YAML catalog adapter (vue-i18n, Rails, and similar).

Structurally the same as ``json-nested``: nested mappings flattened to dotted
keys. Two YAML-specific wrinkles it has to handle.

**A locale-root wrapper.** Rails and vue-i18n conventionally nest the whole file
under its locale code::

    en:
      nav:
        home: Home

That wrapper is not part of the key path, so it is stripped on load and restored
on save. Detection is deliberately narrow -- a single top-level key equal to the
locale -- so a legitimate namespace that happens to share the locale's name is
not mangled.

**Implicit typing.** YAML reads ``yes``, ``no``, ``on``, ``off``, and ``1.0`` as
non-strings. Values are written with explicit quoting so a translation of "No"
does not round-trip into a boolean.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .base import Catalog, FlatMessages
from .json_nested import flatten_messages, unflatten_messages
from .io import atomic_write_text

__all__ = ["YamlNestedCatalog"]


class _QuotedStr(str):
    """Marker so the dumper always quotes translated values."""


def _represent_quoted(dumper: yaml.Dumper, data: _QuotedStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


yaml.add_representer(_QuotedStr, _represent_quoted)
yaml.add_representer(_QuotedStr, _represent_quoted, Dumper=yaml.SafeDumper)


def _quote_all(node):
    if isinstance(node, dict):
        return {k: _quote_all(v) for k, v in node.items()}
    return _QuotedStr(node) if isinstance(node, str) else node


class YamlNestedCatalog(Catalog):
    def __init__(self, root, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        path = self.path_for(locale, namespace)
        return self._cached_load(path, lambda p: self._parse_yaml(p, locale))

    def _parse_yaml(self, path: Path, locale: str) -> FlatMessages:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"{path} is not valid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{path} must contain a mapping at the top level")
        if self._has_locale_root(raw, locale):
            raw = raw[locale]
        return flatten_messages(raw)

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Preserve the file's existing wrapper convention rather than imposing
        # ours: a file that had a locale root keeps it, one that did not stays
        # flat. New files follow the source locale's shape.
        wrap = self._wraps_by_convention(locale, namespace)
        body = _quote_all(unflatten_messages(messages))
        payload = {locale: body} if wrap else body

        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False,
                              default_flow_style=False, width=10_000)
        atomic_write_text(path, text)
        self._bust_cache(path)

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _has_locale_root(raw: dict, locale: str) -> bool:
        return len(raw) == 1 and locale in raw and isinstance(raw[locale], dict)

    def _wraps_by_convention(self, locale: str, namespace: str | None) -> bool:
        for probe_locale in (locale, self.source_locale):
            path = self.path_for(probe_locale, namespace)
            if not path.exists():
                continue
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if isinstance(raw, dict):
                return self._has_locale_root(raw, probe_locale)
        return False
