"""V41: source keys that no scanned code references (C-022, ADR-73)."""

from __future__ import annotations

from ..catalog import Catalog
from ..core.keyglob import key_glob_matches
from ..pipeline.validate import SEVERITY_WARNING, Finding
from ..projects import ProjectConfig
from ..scan import scanner_from_config

__all__ = ["find_unused", "unused_keys"]

_PLURAL_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")


def _bases(key: str) -> list[str]:
    """The key itself, plus the base of a plural-suffixed key (``item_one`` -> ``item``)."""
    out = [key]
    for suffix in _PLURAL_SUFFIXES:
        if key.endswith(suffix):
            out.append(key[: -len(suffix)])
    return out


def unused_keys(
    catalogue: dict[str, list[str]],
    used: set[tuple[str, str]],
    allow: list[str],
) -> list[tuple[str, str]]:
    """Catalogue ``{namespace: [keys]}`` minus used ``(namespace, key)``. Pure.

    A plural-suffixed key counts as used when its base key is. Keys matching an
    ``allow`` glob are never reported.
    """
    out: list[tuple[str, str]] = []
    for ns in sorted(catalogue):
        for key in catalogue[ns]:
            if any((ns, base) in used for base in _bases(key)):
                continue
            if any(key_glob_matches(g, ns, key) for g in allow):
                continue
            out.append((ns, key))
    return out


def find_unused(
    cfg: ProjectConfig, catalog: Catalog, namespaces: list[str] | None,
) -> tuple[list[Finding], str | None]:
    """Findings plus an explanatory note when the check could not run."""
    if not cfg.scan_adapter or not cfg.scan_src_dirs:
        return [], "note: --unused needs [scan] adapter and src_dirs; V41 skipped"
    scanner = scanner_from_config(cfg)
    result = scanner.scan()
    used = {(u.namespace, u.key) for u in result.usages}
    ns_list = list(namespaces) if namespaces else cfg.namespaces_for(catalog)
    catalogue: dict[str, list[str]] = {}
    for ns in ns_list:
        source = catalog.load(cfg.source_locale, ns)
        catalogue[ns] = [
            k for k, v in source.items()
            if not cfg.is_skipped(ns, k, v if isinstance(v, str) else None)
        ]
    path_for = catalog.path_for
    findings = [
        Finding(
            "V41", SEVERITY_WARNING, cfg.source_locale, ns, key,
            f"no scanned code references this key ({result.files_scanned} files scanned)",
            path_for(cfg.source_locale, ns),
        )
        for ns, key in unused_keys(catalogue, used, cfg.scan_unused_allow)
    ]
    return findings, None
