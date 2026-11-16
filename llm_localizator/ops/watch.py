"""``watch``: re-run ``sync`` when a source catalogue file changes.

A foreground convenience for a developer at a keyboard. It is not a daemon and not a
scheduler: it never queues or runs a model (ADR-1), it only gathers the backlog, and it stops
with Ctrl-C. Unattended intake belongs to a queue task or a CI trigger.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from ..catalog import build_catalog, catalog_for
from ..pipeline.sync import run_sync
from ..projects import ProjectConfig

__all__ = ["run_watch", "source_signature"]

Reporter = Callable[[str], None]


def source_signature(cfg: ProjectConfig, catalog) -> dict[str, tuple[int, int]]:
    """``{path: (mtime_ns, size)}`` for every source-locale catalogue file.

    mtime alone misses a rewrite that lands in the same timestamp tick (coarse
    on some filesystems); the size change catches most of those.
    """
    out: dict[str, tuple[int, int]] = {}
    for namespace in cfg.namespaces_for(catalog):
        path = Path(catalog.path_for(cfg.source_locale, namespace))
        try:
            st = path.stat()
            out[str(path)] = (st.st_mtime_ns, st.st_size)
        except OSError:
            out[str(path)] = (0, 0)
    return out


def run_watch(
    cfg: ProjectConfig,
    *,
    interval: float = 5.0,
    diff: bool = False,
    max_cycles: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    report: Reporter = print,
) -> int:
    """Sync once, then again after each change. ``max_cycles`` bounds the polls (tests)."""
    catalog = catalog_for(cfg)
    seen = source_signature(cfg, catalog)
    report(f"watch: syncing now, then every change (poll {interval:g}s; Ctrl-C to stop)")
    run_sync(cfg, catalog, diff=diff, report=report)
    cycles = 0
    try:
        while max_cycles is None or cycles < max_cycles:
            sleep(interval)
            cycles += 1
            catalog = build_catalog(
                cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
            )
            now = source_signature(cfg, catalog)
            if now == seen:
                continue
            changed = sorted(p for p in now if now[p] != seen.get(p))
            report(f"watch: changed {', '.join(Path(p).name for p in changed) or 'files'}")
            seen = now
            run_sync(cfg, catalog, diff=diff, report=report)
    except KeyboardInterrupt:
        report("watch: stopped")
    return 0
