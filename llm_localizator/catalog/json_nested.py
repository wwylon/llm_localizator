"""Nested-JSON catalog adapter (next-intl / react-intl layout).

One file per (locale, namespace); values may be nested objects, which are
flattened to dotted keys on load and restored on save. next-intl supports
dotted ``t()`` keys natively, so both shapes are legitimate in the same file.

Flattening matters for more than tidiness: without it, every function that
assumes ``dict[str, str]`` silently skips nested keys (they fail an
``isinstance(v, str)`` check), so validation never runs on them at all.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Catalog, FlatMessages
from .io import atomic_write_text, load_json_object

__all__ = ["JsonNestedCatalog", "flatten_messages", "unflatten_messages"]


def flatten_messages(d: dict, prefix: str = "") -> FlatMessages:
    """``{"tactics": {"claim": "Claim"}}`` -> ``{"tactics.claim": "Claim"}``."""
    out: FlatMessages = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, str):
            out[key] = v
        elif isinstance(v, dict):
            out.update(flatten_messages(v, key))
    return out


def _opaque_leaves(d: dict, prefix: str = "") -> FlatMessages:
    """Non-string, non-object leaves (numbers, lists, booleans, null) by dotted path.

    They are not translatable, but a save must not delete them.
    """
    out: dict = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_opaque_leaves(v, key))
        elif not isinstance(v, str):
            out[key] = v
    return out


_MAX_UNFLATTEN_DEPTH = 32


def unflatten_messages(flat: FlatMessages) -> dict:
    """Inverse of :func:`flatten_messages`: dotted keys become nested objects.

    A flat map that contains both a scalar and a nested key on the same path
    (``a`` and ``a.b``) is not a tree. Raise instead of dropping one of them.
    """
    root: dict = {}
    for key, val in flat.items():
        parts = key.split(".")
        if len(parts) > _MAX_UNFLATTEN_DEPTH:
            raise ValueError(
                f"key {key!r} exceeds nesting depth {_MAX_UNFLATTEN_DEPTH}"
            )
        cur = root
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            existing = cur.get(part)
            if last:
                if isinstance(existing, dict):
                    child = next(iter(existing), "")
                    other = f"{key}.{child}" if child else key
                    raise ValueError(
                        f"key {key!r} collides with nested key {other!r}"
                    )
                cur[part] = val
                continue
            prefix = ".".join(parts[: i + 1])
            if part not in cur:
                child_node: dict = {}
                cur[part] = child_node
                cur = child_node
            elif isinstance(existing, dict):
                cur = existing
            else:
                raise ValueError(
                    f"key {key!r} collides with scalar key {prefix!r}"
                )
    return root


def _graft(tree: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = tree
    for part in parts[:-1]:
        nxt = cur.setdefault(part, {})
        if not isinstance(nxt, dict):
            raise ValueError(dotted)
        cur = nxt
    if parts[-1] in cur:
        raise ValueError(dotted)
    cur[parts[-1]] = value


class JsonNestedCatalog(Catalog):
    """Message files as nested JSON, one per (locale, namespace)."""

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        return self._cached_load(self.path_for(locale, namespace), self._parse)

    @staticmethod
    def _parse(path: Path) -> FlatMessages:
        return flatten_messages(load_json_object(path))

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        tree = unflatten_messages(messages)
        if path.exists():
            for dotted, value in _opaque_leaves(load_json_object(path)).items():
                if dotted in messages:
                    continue
                try:
                    _graft(tree, dotted, value)
                except ValueError:
                    continue  # a translatable key now owns this path
        payload = json.dumps(tree, ensure_ascii=False, indent=2)
        atomic_write_text(path, payload + "\n")
        self._bust_cache(path)
