"""Match a config glob against a namespace / key. Pure; shared by tiers and ownership."""

from __future__ import annotations

from fnmatch import fnmatchcase

__all__ = ["key_glob_matches"]


def key_glob_matches(pattern: str, namespace: str, key: str) -> bool:
    """``legal/**`` covers the namespace and its children; other globs test the
    namespace, ``namespace.key``, ``namespace/key`` and the bare key."""
    ns = (namespace or "").replace("\\", "/").strip("/")
    if pattern.endswith("/**") and (ns == pattern[:-3] or ns.startswith(pattern[:-2])):
        return True
    return any(fnmatchcase(text, pattern) for text in (ns, f"{ns}.{key}", f"{ns}/{key}", key))
