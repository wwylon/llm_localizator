"""Per-key pixel layout budgets under the engine data home (ADR-159).

Written by the QA crawl (experiments); read by ``validate --check-layout`` (V29)
and optionally by translate/judge prompts. Never requires Playwright in the
installed package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "budget_path",
    "load_budgets",
    "merge_budget",
    "save_budgets",
    "lookup_budget",
]


def budget_path(data_root: Path, locale: str) -> Path:
    """``<data_root>/layout_budgets/<locale>.json``."""
    return Path(data_root) / "layout_budgets" / f"{locale}.json"


def load_budgets(data_root: Path, locale: str) -> dict[str, dict[str, Any]]:
    path = budget_path(data_root, locale)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, val in raw.items():
        if isinstance(key, str) and isinstance(val, dict):
            out[key] = dict(val)
    return out


def save_budgets(data_root: Path, locale: str, budgets: dict[str, dict[str, Any]]) -> Path:
    path = budget_path(data_root, locale)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(budgets, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def merge_budget(
    budgets: dict[str, dict[str, Any]],
    key: str,
    *,
    max_width_px: float | int | None,
    font_size_px: float | int | None = None,
    max_lines: int | None = None,
) -> None:
    """Merge one key: keep the **max** of widths / font sizes seen."""
    if not key or not key.strip():
        return
    sk = key.strip()
    cur = dict(budgets.get(sk) or {})
    if max_width_px is not None:
        try:
            w = float(max_width_px)
        except (TypeError, ValueError):
            w = 0.0
        if w > 0:
            prev = float(cur.get("maxWidthPx") or 0)
            cur["maxWidthPx"] = max(prev, w)
    if font_size_px is not None:
        try:
            fs = float(font_size_px)
        except (TypeError, ValueError):
            fs = 0.0
        if fs > 0:
            prev = float(cur.get("fontSizePx") or 0)
            cur["fontSizePx"] = max(prev, fs)
    if max_lines is not None and max_lines > 0:
        prev = int(cur.get("maxLines") or 0)
        cur["maxLines"] = max(prev, int(max_lines))
    if cur:
        budgets[sk] = cur


def lookup_budget(
    budgets: dict[str, dict[str, Any]],
    namespace: str,
    key: str,
) -> dict[str, Any] | None:
    """Find a budget by ``ns.key`` or flat ``key``."""
    sk = f"{namespace}.{key}" if namespace else key
    hit = budgets.get(sk) or budgets.get(key)
    return dict(hit) if isinstance(hit, dict) else None
