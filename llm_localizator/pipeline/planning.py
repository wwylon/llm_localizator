"""Pure planning helpers for translation work queues."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import TypeVar

from ..core.icu import extract_plural_categories

SHORT_WORD_LIMIT = 4
Item = TypeVar("Item")


def plan_batches(
    items: Sequence[Item],
    batch_size: int,
    *,
    source_of: Callable[[Item], str],
    screen_of: Callable[[Item], str | None],
    short_batch: bool = False,
) -> list[list[Item]]:
    """Partition work into ordered single-item and screen-local batches."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    singles: list[Item] = []
    screen_buckets: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        src = source_of(item)
        is_icu = bool(extract_plural_categories(src))
        is_short = len(src.split()) < SHORT_WORD_LIMIT
        if is_icu or (is_short and not short_batch):
            singles.append(item)
        else:
            screen_buckets[screen_of(item) or "_default"].append(item)

    queues = [[item] for item in singles]
    for screen_items in screen_buckets.values():
        queues.extend(
            screen_items[start : start + batch_size]
            for start in range(0, len(screen_items), batch_size)
        )
    return queues


def pin_run_model(
    items: Sequence[Item],
    *,
    model_for: Callable[[Item], str],
    fallback: str,
) -> tuple[str, set[str]]:
    """Choose one model for a run, preserving the configured fallback."""
    configured = {model_for(item) for item in items}
    if len(configured) == 1:
        return next(iter(configured)), configured
    return fallback, configured


def dry_run_messages(items: Sequence[Item], *, label_of: Callable[[Item], str]) -> list[str]:
    """Build deterministic progress messages for a dry-run preview."""
    total = len(items)
    return [
        f"[{index}/{total}] {label_of(item)} ({round(index / total * 100, 1)}%)"
        for index, item in enumerate(items, 1)
    ]
