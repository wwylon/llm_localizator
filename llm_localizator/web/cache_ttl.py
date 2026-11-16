"""Bounded single-flight TTL cache used by aggregate GET handlers."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class TtlCache(Generic[T]):
    """Generation-aware TTL map with a hard entry cap."""

    def __init__(self, *, ttl_s: float = 30.0, cap: int = 32) -> None:
        self.ttl_s = ttl_s
        self.cap = cap
        self._data: OrderedDict[object, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()
        self.generation = 0

    def invalidate(self) -> None:
        with self._lock:
            self.generation += 1
            self._data.clear()

    def get_or_set(self, key, factory: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit is not None and now - hit[0] < self.ttl_s:
                self._data.move_to_end(key)
                return hit[1]
        value = factory()
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.cap:
                self._data.popitem(last=False)
        return value
