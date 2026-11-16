"""``translate --sample layout[:N]``: a small key set that exercises the layout (P5).

Frozen layout locales (zh for glyph width, ar for right-to-left) do not need the
whole catalogue, only enough text to show what breaks. The sample is:
- the short chrome keys (buttons, tabs, headings: one or two words);
- the longest sources, which overflow first;
- an even spread across namespaces and key prefixes.

The result is deterministic, so reruns pick the same keys.
"""

from __future__ import annotations

import re

from ..catalog import catalog_for
from ..pipeline.scoring import is_risky_key
from ..projects import ProjectConfig

__all__ = ["layout_sample", "parse_sample"]

DEFAULT_SIZE = 60


def parse_sample(spec: str | None) -> int | None:
    """``"layout"`` -> 60, ``"layout:40"`` -> 40, empty -> None; anything else raises."""
    if not spec:
        return None
    m = re.fullmatch(r"layout(?::(\d+))?", spec.strip())
    if not m:
        raise ValueError(f"unknown sample {spec!r}; use layout or layout:N")
    return max(1, int(m.group(1) or DEFAULT_SIZE))


def layout_sample(cfg: ProjectConfig, size: int = DEFAULT_SIZE) -> list[str]:
    """Operator keys (``namespace.key`` or flat) for a layout check, at most ``size``."""
    catalog = catalog_for(cfg)
    rows: list[tuple[str, str]] = []
    for ns in cfg.namespaces_for(catalog):
        for key, src in catalog.load(cfg.source_locale, ns).items():
            if isinstance(src, str) and src.strip() and not cfg.is_skipped(ns, key, src):
                rows.append((f"{ns}.{key}" if ns else key, src))
    if len(rows) <= size:
        return [k for k, _ in rows]
    picked: dict[str, None] = {}

    def take(keys, limit):
        for k in keys:
            if len(picked) >= limit:
                return
            picked.setdefault(k, None)

    third = max(1, size // 3)
    chrome = sorted((k for k, s in rows if is_risky_key(s)), key=lambda k: k)
    take(chrome[:: max(1, len(chrome) // third or 1)], third)
    longest = [k for k, _ in sorted(rows, key=lambda r: (-len(r[1]), r[0]))]
    take(longest, 2 * third)
    groups: dict[str, list[str]] = {}
    for k, _ in rows:
        groups.setdefault(k.split(".", 1)[0], []).append(k)
    spread = [g[i] for i in range(max(len(g) for g in groups.values())) for g in groups.values() if i < len(g)]
    take(spread, size)
    return list(picked)
