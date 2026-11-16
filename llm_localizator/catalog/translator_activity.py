"""Append-only per-user mutation ledger for Team activity (ADR-46).

Lives at ``{state}/translator_activity.jsonl``. Separate from
``.llm-history`` so stats survive per-key history compact.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path

from .io import append_text_line, atomic_write_text
from .jsonl import iter_jsonl_objects
from .state import now_iso

__all__ = [
    "ACTIVITY_NAME",
    "DEFAULT_RETENTION",
    "append_activity",
    "summarize_activity",
]

ACTIVITY_NAME = "translator_activity.jsonl"
DEFAULT_RETENTION = 50_000
#: A row is never shorter than this, so a file smaller than
#: ``retention * _MIN_ROW_BYTES`` cannot exceed *retention* and is not read.
_MIN_ROW_BYTES = 100
#: Past the size gate, re-count lines only every N appends per process.
_TRIM_EVERY = 256
_appends: dict[str, int] = {}


def _path(state_root: Path) -> Path:
    return Path(state_root) / ACTIVITY_NAME


def append_activity(
    state_root: Path,
    *,
    user_id: str,
    username: str,
    locale: str,
    namespace: str,
    key: str,
    trigger: str,
    provider: str | None = None,
    retention: int = DEFAULT_RETENTION,
) -> None:
    """Append one attributed mutation. No-op when *user_id* is empty."""
    uid = str(user_id or "").strip()
    if not uid:
        return
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    path = _path(root)
    row = {
        "ts": now_iso(),
        "user_id": uid,
        "username": str(username or "").strip() or uid,
        "locale": locale,
        "namespace": namespace,
        "key": key,
        "trigger": trigger,
    }
    if provider:
        row["provider"] = provider
    line = json.dumps(row, ensure_ascii=False) + "\n"
    append_text_line(path, line)
    if retention > 0:
        count = _appends.get(str(path), 0)
        _appends[str(path)] = count + 1
        if count % _TRIM_EVERY == 0 or _appends[str(path)] == 1:
            _trim(path, retention)


def _trim(path: Path, retention: int) -> None:
    try:
        if path.stat().st_size < retention * _MIN_ROW_BYTES:
            return
    except OSError:
        return
    keep: deque[str] = deque(maxlen=max(1, retention))
    total = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.rstrip("\n")
                if not stripped:
                    continue
                keep.append(stripped)
                total += 1
    except OSError:
        return
    if total <= retention:
        return
    atomic_write_text(path, "\n".join(keep) + "\n")


def summarize_activity(
    state_root: Path,
    *,
    user_id: str | None = None,
    limit: int = 100,
) -> dict:
    """Aggregate per-user counts by trigger plus a newest-first timeline."""
    path = _path(Path(state_root))
    events: list[dict] = []
    if path.exists():
        for raw, _line in iter_jsonl_objects(path):
            uid = str(raw.get("user_id") or "").strip()
            if not uid:
                continue
            if user_id and uid != user_id:
                continue
            events.append({
                "ts": str(raw.get("ts") or ""),
                "user_id": uid,
                "username": str(raw.get("username") or uid),
                "locale": str(raw.get("locale") or ""),
                "namespace": str(raw.get("namespace") or ""),
                "key": str(raw.get("key") or ""),
                "trigger": str(raw.get("trigger") or ""),
                "provider": raw.get("provider"),
            })

    by_user: dict[str, dict] = {}
    for ev in events:
        uid = ev["user_id"]
        row = by_user.get(uid)
        if row is None:
            row = {
                "user_id": uid,
                "username": ev["username"],
                "total": 0,
                "byTrigger": defaultdict(int),
                "lastAt": ev["ts"],
            }
            by_user[uid] = row
        row["total"] += 1
        row["byTrigger"][ev["trigger"]] += 1
        row["username"] = ev["username"] or row["username"]
        if ev["ts"] >= (row["lastAt"] or ""):
            row["lastAt"] = ev["ts"]

    translators = []
    for row in by_user.values():
        translators.append({
            "user_id": row["user_id"],
            "username": row["username"],
            "total": row["total"],
            "byTrigger": dict(row["byTrigger"]),
            "lastAt": row["lastAt"],
        })
    translators.sort(key=lambda r: (-r["total"], r["username"]))

    timeline = list(reversed(events))
    if limit > 0:
        timeline = timeline[:limit]

    return {
        "ok": True,
        "translators": translators,
        "timeline": timeline,
        "total": len(events),
    }
