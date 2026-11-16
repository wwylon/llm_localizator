"""Catalog interface: how a project's message files are read and written.

A catalog adapter's job is to present any on-disk message format as one flat
mapping of dotted key to string, and to write that mapping back in the format's
native shape. Everything above this layer -- validation, the translation
pipeline, the CLI -- sees only the flat form and never knows whether the source
was nested JSON, gettext, or anything else.

Twelve adapters ship (see ``catalog/__init__.py``: json-nested, json-flat, yaml,
po, arb, android-xml, multilang-json, csv, php-array, go-i18n, ios-strings,
properties). The contract below is what each one implements; a new adapter is
a mechanical exercise, and ``tests/catalog/test_adapter_contract.py`` runs the
shared save/load checks over all of them.

``save`` replaces one locale's content with the mapping it is given (callers
pass the full merged dict). Adapters that rewrite the whole file cannot keep
hand-written comments; they call :func:`warn_comments_lost` once per file.
"""

from __future__ import annotations

import abc
import os
import re
import warnings
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

_WALK_SKIP = frozenset({"node_modules", "__pycache__"})
_CACHE_MAX = 256

__all__ = ["Message", "Catalog", "FlatMessages", "warn_comments_lost"]

FlatMessages = dict[str, str]

_COMMENT_WARNED: set[str] = set()


def warn_comments_lost(path: Path, fmt: str, has_comments) -> None:
    """Warn once per file that a whole-file rewrite will drop its comments.

    *has_comments* is called with the existing file text and returns whether it
    holds comments the adapter will not preserve. Never raises.
    """
    key = str(path)
    if key in _COMMENT_WARNED:
        return
    _COMMENT_WARNED.add(key)
    try:
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if has_comments(text):
            warnings.warn(
                f"{fmt}: saving {path} rewrites the whole file; its comments are not preserved",
                stacklevel=3,
            )
    except OSError:
        pass


@dataclass(frozen=True)
class Message:
    """One translatable unit, with whatever guidance travels alongside it.

    Some formats carry translator guidance *in the file*: gettext has ``#.``
    extracted comments, ARB has ``@key`` description blocks, XLIFF has
    ``<note>``. Others (plain JSON) carry none, and the project supplies notes
    from a sidecar directory instead. ``note`` is where both end up, so the
    prompt builder does not care which kind of project it is looking at.

    ``metadata`` holds anything an adapter must preserve on write but that means
    nothing above the catalog layer -- source references, fuzzy flags, XML
    attributes. Round-tripping a file must not destroy a translator's comments.
    """

    key: str
    value: str
    note: str = ""
    max_chars: int | None = None
    metadata: dict = field(default_factory=dict)


class Catalog(abc.ABC):
    """Reads and writes one project's message files.

    Implementations are constructed with a resolved path template containing
    ``{locale}`` and optionally ``{namespace}``, plus the project root.
    """

    def __init__(self, root: Path, path_template: str, source_locale: str = "en") -> None:
        self.root = Path(root)
        self.path_template = path_template
        self.source_locale = source_locale
        # path → (mtime_ns, payload). Absent files are not stored. Capped at 256.
        self._cache: OrderedDict[str, tuple[int, FlatMessages]] = OrderedDict()

    @staticmethod
    def _validate_component(value: str, label: str) -> None:
        if label == "namespace" and value == "":
            return
        if not isinstance(value, str) or not value or "\\" in value:
            raise ValueError(f"invalid {label}: {value!r}")
        if label == "namespace":
            # ``/`` is a directory separator (``admin/users``). A dot would make
            # the frozen ``{namespace}.{key}`` state key ambiguous (ADR-7).
            if "." in value or value.startswith("/") or value.endswith("/"):
                raise ValueError(f"invalid {label}: {value!r}")
            for part in value.split("/"):
                if not part or part in {".", ".."} or part.startswith("."):
                    raise ValueError(f"invalid {label}: {value!r}")
            return
        if "/" in value or value in {".", ".."}:
            raise ValueError(f"invalid {label}: {value!r}")

    # ---- required of every adapter ----------------------------------------

    def format_locale(self, locale: str) -> str:
        """Path-template locale token. Android overrides this."""
        return locale

    def path_for(self, locale: str, namespace: str | None = None) -> Path:
        """Absolute path of the file holding ``locale``/``namespace``."""
        self._validate_component(locale, "locale")
        if namespace is not None:
            self._validate_component(namespace, "namespace")
        rel = self.path_template.format(
            locale=self.format_locale(locale), namespace=namespace or "",
        )
        return self.root / rel

    def discover_namespaces(self) -> list[str]:
        """Namespaces under the source locale, including nested directories.

        ``messages/en/admin/users.json`` is the namespace ``admin/users``.
        Hidden directories (``.state``, ``.usage``) are skipped. A template
        without ``{namespace}`` is one unnamed namespace.
        """
        if "{namespace}" not in self.path_template:
            return [""]
        probe = self.path_for(self.source_locale, "__NS__")
        base = probe.parent
        if not base.is_dir():
            return []
        suffix = probe.name.replace("__NS__", "")
        names: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [
                name for name in dirnames
                if not name.startswith(".") and name not in _WALK_SKIP
            ]
            for filename in filenames:
                path = Path(dirpath) / filename
                rel_parts = path.relative_to(base).parts
                if any(part.startswith(".") or part in _WALK_SKIP for part in rel_parts):
                    continue
                if suffix:
                    if path.name == suffix or not path.name.endswith(suffix):
                        continue
                    rel = path.relative_to(base).as_posix()
                    ns = rel[: -len(suffix)]
                else:
                    ns = path.relative_to(base).as_posix()
                if ns:
                    names.append(ns)
        return sorted(names)

    @abc.abstractmethod
    def namespaces(self) -> list[str]:
        """Namespaces present in the source locale, sorted.

        A single-file format returns ``[""]`` -- one unnamed namespace.
        """

    @abc.abstractmethod
    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        """Load one file as a flat dotted-key map. Missing file returns ``{}``."""

    @abc.abstractmethod
    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        """Write a flat dotted-key map back in the format's native shape.

        Adapters for formats carrying content we do not model -- comments,
        references, flags -- must read the existing file and merge, so a write
        never destroys a translator's work.
        """

    # ---- optional: native per-key metadata ---------------------------------

    #: Whether this format carries translator notes inside the message file
    #: itself. When False, notes come from the project's ``context_dir``.
    carries_notes: bool = False

    #: Whether the format stores one file per namespace. Single-file formats
    #: report ``[""]`` from :meth:`namespaces` and ignore the argument.
    multi_namespace: bool = True

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        """Load with whatever metadata the format carries natively.

        The default derives entries from :meth:`load`, which is correct for any
        format that stores nothing but key and value.
        """
        return {k: Message(key=k, value=v) for k, v in self.load(locale, namespace).items()}

    # ---- cache helpers -----------------------------------------------------

    def _cached_load(self, path: Path, loader) -> FlatMessages:
        """Call *loader(path)* and cache by path. Value is ``(mtime_ns, payload)``.

        Returns the cached payload when the file has not changed. Absent files
        return ``{}`` and are not cached. At most 256 paths are kept.
        """
        key = str(path)
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            return {}
        # The web server shares one catalogue between request threads (M0, audit ops #31).
        lock = self._cache_lock()
        with lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == mtime:
                self._cache.move_to_end(key)
                return hit[1]
        payload = loader(path)  # outside the lock: a slow parse must not block other files
        with lock:
            self._cache.pop(key, None)
            self._cache[key] = (mtime, payload)
            while len(self._cache) > _CACHE_MAX:
                self._cache.popitem(last=False)
        return payload

    def _cache_lock(self):
        import threading

        lock = self.__dict__.get("_cache_lock_obj")
        if lock is None:
            lock = self.__dict__.setdefault("_cache_lock_obj", threading.Lock())
        return lock

    def invalidate(self) -> None:
        """Drop the in-memory file cache."""
        with self._cache_lock():
            self._cache.clear()

    def _bust_cache(self, path: Path) -> None:
        with self._cache_lock():
            self._cache.pop(str(path), None)

    # ---- shared behaviour --------------------------------------------------

    def locales_present(self) -> list[str]:
        """Target locales discoverable on disk, excluding the source locale.

        Derived from the path template rather than assuming a directory per
        locale, because that assumption does not hold for every format: ARB puts
        the locale in the filename (``app_pl.arb``) and Android puts it in a
        prefixed directory (``values-pl``).
        """
        if not hasattr(self, "_locales_present_regex"):
            _pat = re.escape(self.path_template).replace(r"\{locale\}", "(?P<locale>[^/\\\\]+)")
            _pat = _pat.replace(r"\{namespace\}", r"[^/\\]+")
            self._locales_present_regex = re.compile("^" + _pat + "$")
        regex = self._locales_present_regex

        glob = self.path_template.replace("{locale}", "*").replace("{namespace}", "*")
        found: set[str] = set()
        for path in self.root.glob(glob):
            rel = path.relative_to(self.root).as_posix()
            m = regex.match(rel) or regex.match(rel.replace("/", "\\"))
            if m:
                loc = self.locale_from_path(m.group("locale"))
                if loc.startswith("."):
                    continue
                found.add(loc)
        found.discard(self.source_locale)
        return sorted(found)

    @staticmethod
    def locale_from_path(fragment: str) -> str:
        """Inverse of any locale transformation the adapter applies to paths.

        The identity for most formats; Android overrides it to undo its
        ``pt-rBR`` resource qualifier.
        """
        return fragment

    def merge_for_write(
        self,
        source: FlatMessages,
        existing: FlatMessages,
        updates: FlatMessages,
    ) -> FlatMessages:
        """Rebuild a target file from the source key set.

        **These semantics are load-bearing and golden-tested.** Three rules, in
        order of precedence per key:

        1. a fresh translation in ``updates`` wins;
        2. otherwise an existing translation is preserved;
        3. otherwise the source value is used as a visible fallback.

        And structurally: iteration is over ``source``, so keys absent from the
        source locale are **dropped** -- this is how orphaned keys get pruned
        when an English string is deleted. A target file therefore always has
        exactly the source's key set, which is what keeps every locale
        structurally aligned.
        """
        return {k: updates.get(k, existing.get(k, v)) for k, v in source.items()}

    def write(
        self,
        locale: str,
        namespace: str | None,
        updates: FlatMessages,
        *,
        source: FlatMessages | None = None,
        existing: FlatMessages | None = None,
    ) -> FlatMessages:
        """Merge ``updates`` onto the target and save (orphan-safe).

        Loads source + existing (unless the caller passes what it just loaded), applies
        :meth:`merge_for_write`, then :meth:`save`. Prefer this over bare ``save`` from adopt / push /
        bulk-clear so adapters that share a file still prune orphans.
        """
        src = source if source is not None else self.load(self.source_locale, namespace)
        if existing is None:
            existing = self.load(locale, namespace)
        merged = self.merge_for_write(src, existing, updates)
        self.save(locale, namespace, merged)
        return merged
