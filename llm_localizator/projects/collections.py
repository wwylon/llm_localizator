"""Named text collections.

``[catalog]`` is the collection ``messages``. ``[documents]`` is the collection
``legal``. Further roots live under ``[collections.<name>]``. Omitting a
collection means ``messages``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from ..catalog.io import read_json

__all__ = [
    "Collection",
    "configured_collections",
    "discover_collections",
    "get_collection",
    "list_collection_files",
    "read_collection_file",
    "safe_collection_path",
    "visible_collections",
]

_LOCALE_DIR = re.compile(r"^[a-z]{2,3}([_-][A-Za-z0-9]{2,8})?$")
_DISCOVER_SKIP = {
    "node_modules", ".git", "dist", "build", ".next", ".turbo",
    ".state", ".llm-state", ".llm-history", ".llm-scores", ".usage",
    # Dogfood / verify clones and tool caches — not catalogue trees.
    "experiments", ".venv", "venv", "__pycache__", "vendor", "target",
    "out", "coverage", ".tox", ".mypy_cache", ".pytest_cache", "site-packages",
}


@dataclass(frozen=True)
class Collection:
    name: str
    kind: str
    format: str
    root: Path | None = None


def configured_collections(cfg: ProjectConfig) -> list[Collection]:
    """Collections the operator has confirmed. Discover does not add these."""
    out = [
        Collection(
            name="messages",
            kind="messages",
            format=cfg.catalog_format,
            root=None,
        )
    ]
    if cfg.documents_dir:
        out.append(Collection(
            name="legal",
            kind="files",
            format="markdown",
            root=cfg.documents_dir,
        ))
    seen = {c.name for c in out}
    for name, spec in (getattr(cfg, "collections", None) or {}).items():
        if name in seen or not isinstance(spec, dict):
            continue
        if spec.get("kind") == "remote" or spec.get("format") == "remote":
            out.append(Collection(name=name, kind="remote", format="remote", root=None))
            seen.add(name)
            continue
        rel = spec.get("dir") or spec.get("path")
        root = cfg.resolve(rel) if rel else None
        fmt = str(spec.get("format") or "markdown")
        kind = "messages" if fmt.startswith("json") or fmt in {"po", "arb", "yaml", "android-xml"} else "files"
        out.append(Collection(name=name, kind=kind, format=fmt, root=root))
        seen.add(name)
    return out


def get_collection(cfg: ProjectConfig, name: str | None) -> Collection:
    """Resolve a collection by name.

    Configured collections (``[catalog]``, ``[documents]``, ``[collections]``)
    are checked first so hot paths like ``/api/collection-files`` never walk the
    whole project tree. Discovered-only names still resolve via
    ``visible_collections``.
    """
    wanted = name or "messages"
    for coll in configured_collections(cfg):
        if coll.name == wanted:
            return coll
    visible = visible_collections(cfg)
    for coll in visible:
        if coll.name == wanted:
            return coll
    known = ", ".join(c.name for c in visible) or "(none)"
    raise ValueError(f"unknown collection {wanted!r} (known: {known})")


def _resolved(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        return path.resolve()
    except OSError:
        return path


def _catalog_tree(cfg: ProjectConfig) -> Path | None:
    """Directory whose children are locale folders for the message catalogue."""
    template = cfg.catalog_path or ""
    if "{locale}" not in template:
        return None
    filled = template.replace("{locale}", cfg.source_locale).replace("{namespace}", "__NS__")
    path = cfg.root / filled
    locale_dir = path.parent if path.suffix or "{namespace}" in template else path
    source = cfg.source_locale.replace("_", "-").lower()
    if locale_dir.name.replace("_", "-").lower() == source:
        return locale_dir.parent
    return locale_dir


def visible_collections(cfg: ProjectConfig) -> list[Collection]:
    """Configured collections plus locale trees discover found and nobody claimed.

    ``help`` shows up here without a toml edit. Discover still does not write
    the config. A tree already covered by ``[catalog]`` or ``[documents]`` is
    not listed twice.
    """
    configured = configured_collections(cfg)
    claimed: set[Path] = set()
    for coll in configured:
        resolved = _resolved(coll.root)
        if resolved is not None:
            claimed.add(resolved)
    catalog_tree = _resolved(_catalog_tree(cfg))
    if catalog_tree is not None:
        claimed.add(catalog_tree)
    out = list(configured)
    seen = {c.name for c in out}
    for proposal in discover_collections(cfg.root):
        rel = proposal.get("root") or ""
        root = _resolved(cfg.root / rel if rel else cfg.root)
        if root is None or root in claimed:
            continue
        name = str(proposal.get("name") or rel or "files")
        if name in seen:
            name = rel.replace("/", "-") or name
        if name in seen:
            continue
        fmt = str(proposal.get("format") or "markdown")
        if fmt == "unknown":
            fmt = "markdown"
        out.append(Collection(name=name, kind="files", format=fmt, root=root))
        seen.add(name)
        claimed.add(root)
    return out


def _looks_like_locale(name: str) -> bool:
    return bool(_LOCALE_DIR.match(name))


def _format_of(locale_dir: Path) -> str:
    counts: dict[str, int] = {}
    for path in locale_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(locale_dir).parts):
            continue
        suffix = path.suffix.lower()
        counts[suffix] = counts.get(suffix, 0) + 1
        if len(counts) > 8 and sum(counts.values()) > 40:
            break
    if not counts:
        return "unknown"
    suffix = max(counts, key=counts.get)
    return {
        ".md": "markdown",
        ".markdown": "markdown",
        ".html": "html",
        ".htm": "html",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".po": "po",
        ".arb": "arb",
        ".xml": "android-xml",
        ".php": "php-array",
        ".properties": "properties",
        ".strings": "ios-strings",
        ".stringsdict": "ios-stringsdict",
        ".xcstrings": "xcstrings",
        ".xlf": "xliff",
        ".xliff": "xliff",
    }.get(suffix, suffix.lstrip(".") or "unknown")


def _alias_warnings(names: list[str]) -> list[str]:
    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(name.replace("_", "-").lower(), []).append(name)
    warnings: list[str] = []
    for variants in groups.values():
        if len(set(variants)) > 1:
            shown = ", ".join(sorted(set(variants)))
            warnings.append(
                f"{shown} look like one language written two ways, not a third locale"
            )
    return warnings


def _walk_discover(root: Path):
    """Yield directories, never entering build trees or hidden folders."""
    yield root
    try:
        children = list(root.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir():
            continue
        if child.name in _DISCOVER_SKIP or child.name.startswith("."):
            continue
        yield from _walk_discover(child)


def _multilang_json_locales(raw: dict) -> list[str]:
    """Return locale codes found in a potential multilang-json file, or []."""
    found: set[str] = set()
    for top_val in raw.values():
        if not isinstance(top_val, dict):
            continue
        # Flat shape: {"term": {"pl": "val", "en": "val"}}
        flat_locales = [k for k in top_val if _looks_like_locale(k)]
        if len(flat_locales) >= 2:
            found.update(flat_locales)
            continue
        # Sectioned shape: {"terms": {"trick": {"pl": "val", "en": "val"}}}
        for inner_val in top_val.values():
            if isinstance(inner_val, dict):
                nested_locales = [k for k in inner_val if _looks_like_locale(k)]
                if len(nested_locales) >= 2:
                    found.update(nested_locales)
    return sorted(found)


def _probe_multilang_json(directory: Path, root: Path) -> dict | None:
    """Detect a single JSON file where values (or nested values) have locale-code keys."""
    import json

    try:
        candidates = [f for f in directory.iterdir() if f.is_file() and f.suffix == ".json"
                      and not f.name.startswith(".")]
    except OSError:
        return None
    for path in candidates:
        try:
            raw = read_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(raw, dict):
            continue
        locales = _multilang_json_locales(raw)
        if len(locales) >= 2:
            rel = directory.relative_to(root).as_posix()
            return {
                "name": path.stem,
                "root": rel if rel != "." else "",
                "format": "multilang-json",
                "locales": locales,
                "warnings": [],
                "path_template": path.relative_to(root).as_posix(),
            }
    return None


def _probe_csv(directory: Path, root: Path) -> list[dict]:
    """Detect CSV files whose header row contains locale codes."""
    import csv
    import io

    results = []
    candidates = [f for f in directory.iterdir() if f.is_file() and f.suffix == ".csv"
                  and not f.name.startswith(".")]
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8-sig")
            reader = csv.reader(io.StringIO(text))
            header = next(reader, None)
        except (OSError, UnicodeDecodeError, StopIteration):
            continue
        if not header:
            continue
        locale_cols = [col for col in header if _looks_like_locale(col)]
        if len(locale_cols) >= 2:
            rel = directory.relative_to(root).as_posix()
            results.append({
                "name": path.stem,
                "root": rel if rel != "." else "",
                "format": "csv",
                "locales": sorted(locale_cols),
                "warnings": [],
            })
    return results


def _probe_php_array(directory: Path, root: Path) -> list[dict]:
    """Detect lang/<locale>/<namespace>.php Laravel structure."""
    results = []
    try:
        children = [c for c in directory.iterdir() if c.is_dir() and _looks_like_locale(c.name)]
    except OSError:
        return []
    if len(children) < 2:
        return []
    locales_with_php = []
    for c in children:
        try:
            if any(f.suffix == ".php" for f in c.iterdir() if f.is_file()):
                locales_with_php.append(c)
        except OSError:
            pass
    if len(locales_with_php) < 2:
        return []
    names = sorted(c.name for c in locales_with_php)
    lowered = {n.replace("_", "-").lower() for n in names}
    if "en" not in lowered:
        return []
    rel = directory.relative_to(root).as_posix()
    results.append({
        "name": directory.name,
        "root": rel if rel != "." else "",
        "format": "php-array",
        "locales": names,
        "warnings": _alias_warnings(names),
    })
    return results


def _probe_go_i18n(directory: Path, root: Path) -> list[dict]:
    """Detect go-i18n JSON files (array of {id, translation} objects)."""
    import json

    results = []
    try:
        candidates = [
            f for f in directory.iterdir()
            if f.is_file() and f.suffix == ".json" and _looks_like_locale(f.stem)
        ]
    except OSError:
        return []
    go_i18n_files = []
    for path in candidates:
        try:
            raw = read_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "id" in raw[0]:
            go_i18n_files.append(path.stem)
    if len(go_i18n_files) < 2:
        return []
    rel = directory.relative_to(root).as_posix()
    results.append({
        "name": directory.name,
        "root": rel if rel != "." else "",
        "format": "go-i18n",
        "locales": sorted(go_i18n_files),
        "warnings": _alias_warnings(go_i18n_files),
    })
    return results


def _probe_ios_strings(directory: Path, root: Path) -> list[dict]:
    """Detect *.lproj/Localizable.strings Apple structure."""
    import re

    _LPROJ_RE = re.compile(r"^(.+)\.lproj$", re.IGNORECASE)
    results = []
    try:
        lproj_dirs = [d for d in directory.iterdir() if d.is_dir() and _LPROJ_RE.match(d.name)]
    except OSError:
        return []
    if len(lproj_dirs) < 2:
        return []
    locales = []
    for d in lproj_dirs:
        m = _LPROJ_RE.match(d.name)
        locale = m.group(1) if m else d.name
        # Normalise Base → en for detection purposes
        if locale.lower() == "base":
            continue
        if any(f.suffix == ".strings" for f in d.iterdir() if f.is_file()):
            locales.append(locale)
    if len(locales) < 2:
        return []
    rel = directory.relative_to(root).as_posix()
    results.append({
        "name": directory.name,
        "root": rel if rel != "." else "",
        "format": "ios-strings",
        "locales": sorted(locales),
        "warnings": [],
    })
    return results


def _probe_properties(directory: Path, root: Path) -> list[dict]:
    """Detect messages_<locale>.properties Spring/Java structure."""
    import re

    _PROPS_RE = re.compile(r"^(.+)_([a-z]{2,3}([_-][A-Za-z0-9]{2,8})?)\.properties$")
    results = []
    try:
        props_files = [f for f in directory.iterdir() if f.is_file() and f.suffix == ".properties"]
    except OSError:
        return []
    # Group by base name
    groups: dict[str, list[str]] = {}
    for f in props_files:
        m = _PROPS_RE.match(f.name)
        if m:
            base = m.group(1)
            locale = m.group(2)
            groups.setdefault(base, []).append(locale)
    for base, locales in groups.items():
        if len(locales) < 2:
            continue
        rel = directory.relative_to(root).as_posix()
        results.append({
            "name": base,
            "root": rel if rel != "." else "",
            "format": "properties",
            "locales": sorted(locales),
            "warnings": _alias_warnings(locales),
        })
    return results


def discover_collections(root: Path) -> list[dict]:
    """Propose collections. Does not write config (ADR-3).

    A locale-named sibling directory, with the source locale present, is the
    usual signal. ``node_modules`` and other build trees are ignored.  Additional
    probes detect alternative formats (multilang-json, CSV, PHP array, go-i18n,
    iOS .strings, Java .properties).
    """
    root = Path(root)
    proposals: list[dict] = []
    seen_roots: set[str] = set()
    if not root.is_dir():
        return proposals
    for directory in _walk_discover(root):
        # Standard per-locale-directory probe
        try:
            children = [c for c in directory.iterdir() if c.is_dir() and _looks_like_locale(c.name)]
        except OSError:
            continue
        if len(children) >= 2:
            names = sorted(c.name for c in children)
            lowered = {n.replace("_", "-").lower() for n in names}
            if "en" in lowered:
                sample = next(c for c in children if c.name.replace("_", "-").lower() == "en")
                fmt = _format_of(sample)
                rel = directory.relative_to(root).as_posix()
                if rel == ".":
                    rel = ""
                key = rel or "."
                if key not in seen_roots:
                    name = directory.name if rel else root.name
                    proposals.append({
                        "name": name,
                        "root": rel,
                        "format": fmt,
                        "locales": names,
                        "warnings": _alias_warnings(names),
                    })
                    seen_roots.add(key)

        # Additional format probes
        ml = _probe_multilang_json(directory, root)
        if ml:
            key = (ml.get("root") or "") + "/" + ml.get("path_template", "")
            if key not in seen_roots:
                proposals.append(ml)
                seen_roots.add(key)

        for p in _probe_csv(directory, root):
            key = (p.get("root") or "") + "/" + p.get("name", "")
            if key not in seen_roots:
                proposals.append(p)
                seen_roots.add(key)

        for p in _probe_php_array(directory, root):
            key = p.get("root") or "."
            if key not in seen_roots:
                proposals.append(p)
                seen_roots.add(key)

        for p in _probe_go_i18n(directory, root):
            key = (p.get("root") or ".") + "/go-i18n"
            if key not in seen_roots:
                proposals.append(p)
                seen_roots.add(key)

        for p in _probe_ios_strings(directory, root):
            key = (p.get("root") or ".") + "/ios-strings"
            if key not in seen_roots:
                proposals.append(p)
                seen_roots.add(key)

        for p in _probe_properties(directory, root):
            key = (p.get("root") or ".") + "/" + p.get("name", "")
            if key not in seen_roots:
                proposals.append(p)
                seen_roots.add(key)

    return proposals


def list_collection_files(
    cfg: ProjectConfig,
    name: str,
    locales: list[str] | None = None,
) -> list[dict]:
    """Path, presence, and stale flag for one file collection. Not the key table."""
    coll = get_collection(cfg, name)
    if coll.kind == "remote":
        raise ValueError(
            f"collection {name!r} is a remote content API, not a file list; use status"
        )
    if coll.kind == "messages" or coll.root is None:
        raise ValueError(f"collection {name!r} is a message catalogue, not a file list")
    source_dir = coll.root / cfg.source_locale
    if not source_dir.is_dir():
        return []
    wanted = locales or list(cfg.targets)
    rows: list[dict] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(source_dir).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        rel = path.relative_to(source_dir).as_posix()
        source_mtime = path.stat().st_mtime
        per_locale: dict[str, dict] = {}
        for locale in wanted:
            target = coll.root / locale / rel
            present = target.is_file()
            stale = bool(present and target.stat().st_mtime + 1 < source_mtime)
            per_locale[locale] = {"present": present, "stale": stale}
        present_n = sum(1 for item in per_locale.values() if item["present"] and not item["stale"])
        rows.append({
            "path": rel,
            "coverage": (present_n / len(wanted)) if wanted else 0.0,
            "locales": per_locale,
        })
    return rows


def safe_collection_path(cfg: ProjectConfig, name: str, locale: str, rel: str) -> Path:
    """Resolve one file inside a collection. Rejects paths that leave the root."""
    coll = get_collection(cfg, name)
    if coll.root is None:
        raise ValueError(f"collection {name!r} has no directory")
    if not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        raise ValueError(f"invalid path {rel!r}")
    root = (coll.root / locale).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"invalid path {rel!r}")
    return path


def read_collection_file(cfg: ProjectConfig, name: str, locale: str, rel: str) -> str:
    path = safe_collection_path(cfg, name, locale, rel)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")
