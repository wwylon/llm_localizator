"""Per-cell approval test for delivery (C-007, ADR-74)."""
from __future__ import annotations

from .review_queue import open_review_queue
from .state import StateStore, is_verified

__all__ = ["approval_checker", "DELIVERY_LEVELS"]

DELIVERY_LEVELS = ("none", "verified", "reviewed")


def approval_checker(cfg, *, force: bool = False):
    """Return ``ok(locale, namespace, key)``.

    ``verified``: the cell carries a verification stamp. ``reviewed``: verified
    and no open review ticket. ``force`` with level ``none`` behaves as ``verified``.
    """
    level = getattr(cfg, "delivery_require", "none")
    if level == "none":
        if not force:
            return lambda *_a: True
        level = "verified"
    state = StateStore(cfg.state_root())
    queue = open_review_queue(cfg) if level == "reviewed" else None

    def ok(locale: str, namespace: str, key: str) -> bool:
        if not is_verified(state.entry(locale, namespace, key)):
            return False
        return queue is None or queue.find_open(locale, namespace, key) is None

    return ok
