"""Journaled multi-sidecar flush protocol (audit follow-on / ADR-26).

Before writing catalogue/state/scores/history, record an intent journal. On
success the journal is cleared or left in ``phase=progress`` with the last
finished key (W-12 / F.8). On startup, a leftover flush phase marks an
interrupted flush for recovery/inspection. ``phase=progress`` is not a block.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .io import atomic_write_text
from .state import now_iso
from .io import read_json

__all__ = ["FlushJournal", "FlushIntent", "JOURNAL_NAME", "flush_block_message"]

JOURNAL_NAME = "_flush_journal.json"

# Phases that mean a mid-flush crash — mutators must stop.
_BLOCKING_PHASES = frozenset({
    "started", "catalog", "state", "scores", "history",
})


@dataclass
class FlushIntent:
    run_id: str
    started_at: str
    locales: list[str] = field(default_factory=list)
    namespaces: list[str] = field(default_factory=list)
    pending_keys: int = 0
    history_events: int = 0
    phase: str = "started"  # started | catalog | state | scores | history | done | progress
    last_finished: list[str] = field(default_factory=list)  # [locale, namespace, key]


class FlushJournal:
    """Single-file journal under ``state_root``."""

    def __init__(self, state_root: Path) -> None:
        self.root = Path(state_root)
        self.path = self.root / JOURNAL_NAME
        # In-memory copy of what this instance last wrote (write-through). The
        # mutation lock (ADR-24) makes this process the only writer during a
        # flush, so set_phase need not re-read the file. Crash recovery still
        # reads the file (read / interrupted / last_finished_key).
        self._written: dict[str, Any] | None = None

    def _write(self, raw: dict[str, Any]) -> None:
        atomic_write_text(
            self.path, json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        )
        self._written = raw

    def begin(self, intent: FlushIntent) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._write(asdict(intent))

    def set_phase(self, phase: str) -> None:
        # The cached intent is trusted only while its file exists; an external
        # delete (acknowledge-flush) still makes this a no-op, as before.
        if self._written is not None and self.path.exists():
            raw = dict(self._written)
        else:
            raw = self.read()
        if raw is None:
            self._written = None
            return
        raw["phase"] = phase
        self._write(raw)

    def note_progress(
        self,
        flushed: list[tuple[str, str, str]],
        *,
        run_id: str = "",
    ) -> None:
        """Record the last finished key after a successful batch flush.

        Leaves ``phase=progress`` so the next translate can see progress without
        blocking mutators. Does not invent a second journal file.
        """
        if not flushed:
            self.clear()
            return
        locale, namespace, key = flushed[-1]
        intent = FlushIntent(
            run_id=run_id or "translate",
            started_at=now_iso(),
            locales=[locale],
            namespaces=[namespace],
            pending_keys=0,
            history_events=0,
            phase="progress",
            last_finished=[locale, namespace, key],
        )
        self.begin(intent)

    def clear(self) -> None:
        self._written = None
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return read_json(self.path)
        except (OSError, json.JSONDecodeError):
            return None

    def last_finished_key(self) -> tuple[str, str, str] | None:
        """Return ``(locale, namespace, key)`` from a progress record, if any."""
        raw = self.read()
        if not raw:
            return None
        parts = raw.get("last_finished") or []
        if len(parts) != 3:
            return None
        return str(parts[0]), str(parts[1]), str(parts[2])

    def interrupted(self) -> FlushIntent | None:
        """Return a leftover intent if a prior flush did not finish."""
        raw = self.read()
        if not raw:
            return None
        phase = str(raw.get("phase") or "started")
        if phase == "done" or phase == "progress" or phase not in _BLOCKING_PHASES:
            return None
        try:
            return FlushIntent(
                run_id=str(raw.get("run_id") or ""),
                started_at=str(raw.get("started_at") or now_iso()),
                locales=list(raw.get("locales") or []),
                namespaces=list(raw.get("namespaces") or []),
                pending_keys=int(raw.get("pending_keys") or 0),
                history_events=int(raw.get("history_events") or 0),
                phase=phase,
                last_finished=list(raw.get("last_finished") or []),
            )
        except (TypeError, ValueError):
            return None

    def acknowledge(self) -> bool:
        """Delete the journal. Does not write catalogues. Returns whether a file was removed."""
        existed = self.path.exists()
        self.clear()
        return existed and not self.path.exists()


def flush_block_message(state_root: Path) -> str | None:
    """Non-empty when translate, improve, or import must stop."""
    intent = FlushJournal(state_root).interrupted()
    if intent is None:
        return None
    return (
        f"interrupted flush from {intent.started_at} phase={intent.phase}; "
        "run `llm-localizator acknowledge-flush` (it deletes the journal and "
        "does not write catalogues)"
    )
