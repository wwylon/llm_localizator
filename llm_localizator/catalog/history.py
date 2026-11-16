"""Append-only translation history for automated rollback.

Stored beside state as ``.llm-history/<locale>.jsonl``. Does not alter ADR-7
state records. Retention is capped per key so files stay bounded.
"""

from __future__ import annotations

import json
from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .state import now_iso, state_key
from .io import append_text_line, rewrite_text_locked

__all__ = ["HistoryEvent", "HistoryStore", "DEFAULT_RETENTION", "make_history_event"]

DEFAULT_RETENTION = 20


_REQUIRED_HISTORY_FIELDS = (
    "ts", "namespace", "key", "next", "model", "status", "src_sha", "trigger",
)


def _parse_history_line(line: str, fields) -> tuple[str, HistoryEvent, dict] | None:
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    for name in _REQUIRED_HISTORY_FIELDS:
        value = raw.get(name)
        if value is None or (isinstance(value, str) and not value and name not in ("next", "namespace")):
            return None
    if not isinstance(raw.get("namespace"), str) or not isinstance(raw.get("key"), str):
        return None
    if not isinstance(raw.get("trigger"), str) or not raw["trigger"]:
        return None
    sk = state_key(str(raw.get("namespace") or ""), str(raw.get("key") or ""))
    try:
        event = HistoryEvent(**{k: raw.get(k) for k in fields})
    except TypeError:
        return None
    return sk, event, raw


@dataclass
class HistoryEvent:
    ts: str
    namespace: str
    key: str
    prev: str | None
    next: str
    model: str
    status: str
    src_sha: str
    trigger: str
    quality_score: float | None = None
    provider: str | None = None
    candidates: list[dict] | None = None
    propagated_from: str | None = None
    edited_by: str | None = None
    edited_by_name: str | None = None
    prev_src: str | None = None
    next_src: str | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        if not payload.get("prev_src"):
            payload.pop("prev_src", None)
            payload.pop("next_src", None)
        if payload.get("provider") is None:
            payload.pop("provider", None)
        if not payload.get("candidates"):
            payload.pop("candidates", None)
        if not payload.get("propagated_from"):
            payload.pop("propagated_from", None)
        if not payload.get("edited_by"):
            payload.pop("edited_by", None)
        if not payload.get("edited_by_name"):
            payload.pop("edited_by_name", None)
        return json.dumps(payload, ensure_ascii=False)


class HistoryStore:
    def __init__(self, directory: Path, *, retention: int = DEFAULT_RETENTION) -> None:
        self.dir = Path(directory)
        self.retention = retention
        # locale → (mtime_ns, latest-by-key map); capped at 10 locales (LRU)
        self._latest_cache: OrderedDict[str, tuple[int, dict[str, HistoryEvent]]] = OrderedDict()
        self._latest_cache_max = 10

    def path_for(self, locale: str) -> Path:
        return self.dir / f"{locale}.jsonl"

    def invalidate(self, locale: str | None = None) -> None:
        if locale is None:
            self._latest_cache.clear()
        else:
            self._latest_cache.pop(locale, None)

    def _iter_events(self, locale: str):  # noqa: D401 - kept alias, see iter_events
        return self.iter_events(locale)

    def iter_events(self, locale: str):
        """Yield ``(state_key, event, raw)`` for each parseable line."""
        path = self.path_for(locale)
        if not path.exists():
            return
        fields = HistoryEvent.__dataclass_fields__
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    parsed = _parse_history_line(line, fields)
                    if parsed is not None:
                        yield parsed
        except OSError:
            return

    def append(self, locale: str, event: HistoryEvent) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(locale)
        append_text_line(path, event.to_json())
        self.invalidate(locale)

    def compact(self, locale: str) -> None:
        """Apply retention after a batch or at process shutdown."""
        self._compact(locale)
        self.invalidate(locale)

    def events_for(
        self, locale: str, namespace: str, key: str, *, limit: int | None = None,
    ) -> list[HistoryEvent]:
        # Editor history often asks for the latest event only — reuse the
        # mtime-cached latest-by-key index.
        if limit is not None and 0 < limit <= 1:
            latest = self.latest_by_key(locale).get(state_key(namespace, key))
            return [latest] if latest is not None else []
        sk = state_key(namespace, key)
        out: list[HistoryEvent] = []
        path = self.path_for(locale)
        if not path.exists():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = _parse_history_line(line, HistoryEvent.__dataclass_fields__)
            if parsed is not None and parsed[0] == sk:
                out.append(parsed[1])
        if limit is not None and limit > 0:
            return out[-limit:]
        return out

    def latest(self, locale: str, namespace: str, key: str) -> HistoryEvent | None:
        ev = self.events_for(locale, namespace, key, limit=1)
        return ev[-1] if ev else None

    def latest_by_key(self, locale: str) -> dict[str, HistoryEvent]:
        """Map ``state_key`` → most recent history event (one linear scan)."""
        path = self.path_for(locale)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = -1
        hit = self._latest_cache.get(locale)
        if hit is not None and hit[0] == mtime:
            self._latest_cache.move_to_end(locale)
            return hit[1]
        out: dict[str, HistoryEvent] = {}
        for sk, event, _raw in self._iter_events(locale):
            out[sk] = event
        self._latest_cache[locale] = (mtime, out)
        self._latest_cache.move_to_end(locale)
        while len(self._latest_cache) > self._latest_cache_max:
            self._latest_cache.popitem(last=False)
        return out

    def latest_by_triggers(
        self, locale: str, triggers: frozenset[str],
    ) -> dict[str, HistoryEvent]:
        """Map ``state_key`` → latest event whose ``trigger`` is in ``triggers``."""
        out: dict[str, HistoryEvent] = {}
        if not triggers:
            return out
        for sk, event, raw in self._iter_events(locale):
            if raw.get("trigger") not in triggers:
                continue
            out[sk] = event
        return out

    def _compact(self, locale: str) -> None:
        path = self.path_for(locale)
        if not path.exists():
            return
        by_key: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
        total = 0
        seq = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            sk = state_key(str(raw.get("namespace") or ""), str(raw.get("key") or ""))
            ts = str(raw.get("ts") or "")
            by_key[sk].append((seq, ts, line))
            seq += 1
        retained: list[tuple[int, str, str]] = []
        for rows in by_key.values():
            retained.extend(rows[-self.retention :])
        # Keep global chronological order (ts, then original sequence).
        retained.sort(key=lambda item: (item[1], item[0]))
        lines = [item[2] for item in retained]
        if len(lines) == total:
            return  # nothing to drop: skip the whole-file rewrite
        rewrite_text_locked(path, "\n".join(lines) + ("\n" if lines else ""))


def make_history_event(
    *,
    namespace: str,
    key: str,
    prev: str | None,
    next_text: str,
    model: str,
    status: str,
    src_sha: str,
    trigger: str,
    quality_score: float | None = None,
    provider: str | None = None,
    candidates: list[dict] | None = None,
    propagated_from: str | None = None,
    edited_by: str | None = None,
    edited_by_name: str | None = None,
    prev_src: str | None = None,
    next_src: str | None = None,
) -> HistoryEvent:
    from .provenance import normalize_provider

    return HistoryEvent(
        prev_src=prev_src or None,
        next_src=next_src if prev_src else None,
        ts=now_iso(),
        namespace=namespace,
        key=key,
        prev=prev,
        next=next_text,
        model=model,
        status=status,
        src_sha=src_sha,
        trigger=trigger,
        quality_score=quality_score,
        provider=normalize_provider(provider) if provider is not None else None,
        candidates=candidates or None,
        propagated_from=propagated_from or None,
        edited_by=(str(edited_by).strip() or None) if edited_by else None,
        edited_by_name=(str(edited_by_name).strip() or None) if edited_by_name else None,
    )
