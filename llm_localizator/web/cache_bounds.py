"""Bounded caches and lock maps for the long-lived review server (Wave B2)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TypeVar

__all__ = [
    "STATES_CAP",
    "LOCK_MAP_CAP",
    "bounded_put",
    "bounded_lock",
]

STATES_CAP = 8  # default project + a handful of recently selected ones
LOCK_MAP_CAP = 64

K = TypeVar("K")
V = TypeVar("V")


def bounded_put(cache: OrderedDict[K, V] | dict[K, V], key: K, value: V, *, cap: int) -> None:
    """Insert ``key`` and drop the oldest entries when over ``cap``."""
    if isinstance(cache, OrderedDict):
        cache.pop(key, None)
        cache[key] = value
        while len(cache) > cap:
            cache.popitem(last=False)
        return
    cache.pop(key, None)
    cache[key] = value
    while len(cache) > cap:
        cache.pop(next(iter(cache)))


def bounded_lock(
    locks: dict[K, threading.Lock],
    key: K,
    *,
    guard: threading.Lock,
    cap: int = LOCK_MAP_CAP,
) -> threading.Lock:
    """Return a per-key Lock, pruning idle keys when the map grows past ``cap``."""
    with guard:
        lock = locks.get(key)
        if lock is None:
            lock = threading.Lock()
            locks[key] = lock
        # Move to end when OrderedDict; plain dict just caps by FIFO of keys().
        if isinstance(locks, OrderedDict):
            locks.move_to_end(key)
            while len(locks) > cap:
                # Never drop a lock that is held — skip locked entries.
                oldest_key, oldest = next(iter(locks.items()))
                if oldest.locked():
                    locks.move_to_end(oldest_key)
                    if all(v.locked() for v in locks.values()):
                        break
                    continue
                locks.popitem(last=False)
        else:
            while len(locks) > cap:
                victim = next(iter(locks))
                if locks[victim].locked():
                    break
                locks.pop(victim, None)
        return lock


# AppState eviction lives in server_logic._prune_states (OrderedDict + pin
# default project). A separate StateLRU was unused and removed.