"""Monthly API spend ledger for cloud translation providers.

Cross-process safe: every read-modify-write takes ``.spend.lock`` under the
budget root (same flock/msvcrt scheme as ADR-24). Pre-flight callers
``reserve`` a ceiling so concurrent runs cannot both see the same remaining
balance; ``record`` meters actual spend and ``release`` drops unused hold.
"""

from __future__ import annotations

import json
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .io import atomic_write_text
from .mutation_lock import mutation_lock
from .pricing import token_usd
from .io import read_json

__all__ = ["BudgetStore", "estimate_anthropic_usd"]

_MAX_EVENTS = 5000
_LOCK_NAME = ".spend.lock"


def estimate_anthropic_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD for an Anthropic call. Unknown models raise; they are not priced as Haiku."""
    return token_usd(model, input_tokens, output_tokens)


class BudgetStore:
    """Append-only monthly spend at ``<root>/spend.json``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "spend.json"
        self._lock = threading.Lock()

    def _month_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    @contextmanager
    def _ledger(self) -> Iterator[None]:
        """In-process then cross-process exclusion for ledger RMW."""
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with mutation_lock(self.root / _LOCK_NAME, timeout_s=60.0):
                yield

    def _load(self, strict: bool = False) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = read_json(self.path)
        except (OSError, json.JSONDecodeError) as exc:
            if strict:
                # record() must not persist {} over an unreadable ledger: that
                # would erase spend history (and the cap that depends on it).
                raise RuntimeError(f"spend ledger unreadable: {self.path} ({exc})") from exc
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def _row(self, data: dict, key: str) -> dict:
        row = data.setdefault(key, {"total_usd": 0.0, "events": [], "holds": {}})
        if not isinstance(row.get("holds"), dict):
            row["holds"] = {}
        return row

    def _reserved(self, row: dict) -> float:
        holds = row.get("holds") or {}
        return round(sum(float(v) for v in holds.values() if isinstance(v, (int, float))), 6)

    def _remaining_unlocked(self, row: dict, cap_usd: float) -> float:
        spent = float(row.get("total_usd", 0.0))
        return max(0.0, float(cap_usd) - spent - self._reserved(row))

    def month_total(self, month: str | None = None) -> float:
        key = month or self._month_key()
        with self._ledger():
            row = self._load().get(key) or {}
            return float(row.get("total_usd", 0.0))

    def months(self) -> list[str]:
        """Month keys present in the ledger, oldest first."""
        with self._ledger():
            return sorted(k for k in self._load() if isinstance(k, str))

    def events(self, month: str | None = None) -> list[dict]:
        """Ledger events for ``month`` (default: current). Old events lack kind/tokens."""
        with self._ledger():
            row = self._load().get(month or self._month_key()) or {}
            found = row.get("events") if isinstance(row, dict) else None
            return [e for e in (found or []) if isinstance(e, dict)]

    def remaining(self, cap_usd: float) -> float:
        with self._ledger():
            row = self._load().get(self._month_key()) or {}
            return self._remaining_unlocked(row if isinstance(row, dict) else {}, cap_usd)

    def reserve(self, amount_usd: float, *, cap_usd: float) -> str | None:
        """Hold ``amount_usd`` against the monthly cap. Returns a hold id, or None."""
        amount = float(amount_usd)
        if amount <= 0 or float(cap_usd) <= 0:
            return None
        with self._ledger():
            data = self._load(strict=True)
            key = self._month_key()
            row = self._row(data, key)
            if self._remaining_unlocked(row, cap_usd) < amount:
                return None
            hold_id = secrets.token_hex(8)
            row["holds"][hold_id] = round(amount, 6)
            self._save(data)
            return hold_id

    def release(self, hold_id: str | None) -> None:
        """Drop an unused (or leftover) reservation."""
        if not hold_id:
            return
        with self._ledger():
            data = self._load(strict=True)
            key = self._month_key()
            row = data.get(key)
            if not isinstance(row, dict):
                return
            holds = row.get("holds")
            if not isinstance(holds, dict) or hold_id not in holds:
                return
            del holds[hold_id]
            self._save(data)

    def record(
        self, amount_usd: float, *, locale: str, model: str, note: str = "",
        kind: str = "", input_tokens: int | None = None,
        output_tokens: int | None = None, characters: int | None = None,
    ) -> float:
        # Always meter a call that already happened, even past the monthly
        # cap — remaining()/reserve refuse new work; the ledger stays truthful.
        if amount_usd <= 0:
            return self.month_total()
        with self._ledger():
            data = self._load(strict=True)
            key = self._month_key()
            row = self._row(data, key)
            amount = float(amount_usd)
            row["total_usd"] = round(float(row.get("total_usd", 0.0)) + amount, 6)
            events = row.setdefault("events", [])
            event = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "usd": round(amount, 6),
                "locale": locale,
                "model": model,
                "note": note,
            }
            if kind:
                event["kind"] = kind
            if input_tokens is not None:
                event["input_tokens"] = int(input_tokens)
            if output_tokens is not None:
                event["output_tokens"] = int(output_tokens)
            if characters is not None:
                event["characters"] = int(characters)
            events.append(event)
            if len(events) > _MAX_EVENTS:
                row["events"] = events[-_MAX_EVENTS:]
            self._save(data)
            return float(row["total_usd"])
