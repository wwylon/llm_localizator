"""Source-code scanners."""

from __future__ import annotations

from pathlib import Path

from .base import HardcodedString, Scanner, ScanResult, Usage
from .next_intl import NextIntlScanner
from .raw_js import RawJsScanner
from .source import SourceScanner

__all__ = [
    "HardcodedString",
    "NextIntlScanner",
    "RawJsScanner",
    "ScanResult",
    "Scanner",
    "SourceScanner",
    "Usage",
    "build_scanner",
    "scanner_names",
]

_SCANNERS: dict[str, type[Scanner]] = {
    "next-intl": NextIntlScanner,
    # react-intl uses the same t()/useTranslations surface in practice.
    "react-intl": NextIntlScanner,
    "raw-js": RawJsScanner,
    "source": SourceScanner,
}


def scanner_names() -> list[str]:
    """Registered source adapters. A new language is a new name here."""
    return sorted(_SCANNERS)


def build_scanner(
    name: str,
    root: Path,
    src_dirs: list[str],
    *,
    exclude: list[str] | None = None,
    unskip: list[str] | None = None,
    t_functions: list[str] | None = None,
    content_globs: list[str] | None = None,
) -> Scanner:
    try:
        cls = _SCANNERS[name]
    except KeyError:
        known = ", ".join(sorted(_SCANNERS))
        raise ValueError(f"unknown scan adapter {name!r} (known: {known})") from None
    scanner = cls(root, src_dirs, exclude=exclude, unskip=unskip)
    scanner.t_functions = tuple(str(n).strip() for n in (t_functions or []) if str(n).strip())
    scanner.content_globs = tuple(str(g).strip() for g in (content_globs or []) if str(g).strip())
    return scanner


def scanner_from_config(cfg, adapter: str | None = None) -> Scanner:
    """The project's scanner with every ``[scan]`` setting applied (one place for all ops; M3).

    Raises ``ValueError`` for an unknown adapter, like ``build_scanner``.
    """
    scanner = build_scanner(
        adapter or cfg.scan_adapter, cfg.root, cfg.scan_src_dirs,
        exclude=cfg.scan_exclude, unskip=cfg.scan_unskip,
        t_functions=cfg.scan_t_functions, content_globs=cfg.scan_content_globs,
    )
    scanner.directive_aliases = cfg.scan_directive_aliases
    return scanner


def scan_settings(cfg, adapter: str | None = None) -> list:
    """The ``[scan]`` settings a cached scan result depends on, in a stable, JSON-friendly order."""
    return [
        adapter or cfg.scan_adapter, sorted(cfg.scan_exclude), sorted(cfg.scan_unskip),
        sorted(cfg.scan_t_functions), sorted(cfg.scan_content_globs), bool(cfg.scan_directive_aliases),
    ]
