"""Per-run reproducibility and speed analytics manifest (ADR-25 / ADR-37)."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..catalog.io import atomic_write_text
from ..catalog.state import now_iso, parse_translated_at
from ..catalog.io import read_json

__all__ = [
    "RunManifest",
    "config_fingerprint",
    "iter_run_records",
    "latest_run_record",
    "load_run_record",
]


def config_fingerprint(payload: dict[str, Any]) -> str:
    """Stable short hash of selected config fields."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class RunManifest:
    """One translate/improve/review/rescore execution — written beside state."""

    run_id: str
    started_at: str
    command: str
    locales: list[str] = field(default_factory=list)
    model: str | None = None
    prompt_family: str | None = None
    config_hash: str = ""
    source_locale: str = "en"
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    finished_at: str | None = None
    wall_s: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    _t0: float = field(default=0.0, repr=False, compare=False)

    @classmethod
    def start(
        cls,
        *,
        command: str,
        locales: list[str] | None = None,
        model: str | None = None,
        prompt_family: str | None = None,
        config_hash: str = "",
        source_locale: str = "en",
    ) -> RunManifest:
        manifest = cls(
            run_id=uuid.uuid4().hex[:12],
            started_at=now_iso(),
            command=command,
            locales=list(locales or []),
            model=model,
            prompt_family=prompt_family,
            config_hash=config_hash,
            source_locale=source_locale,
        )
        manifest._t0 = time.perf_counter()
        return manifest

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def finish(self, **metrics: Any) -> None:
        """Close the run and merge speed / context metrics."""
        self.finished_at = now_iso()
        if self._t0:
            self.wall_s = round(time.perf_counter() - self._t0, 3)
        elif self.started_at:
            started = parse_translated_at(self.started_at)
            finished = parse_translated_at(self.finished_at)
            if started and finished:
                self.wall_s = round(
                    (finished - started).total_seconds(), 3,
                )
        self.metrics.update({k: v for k, v in metrics.items() if v is not None})
        self._apply_rate_metrics()

    def _apply_rate_metrics(self) -> None:
        if not self.wall_s or self.wall_s <= 0:
            return
        cmd = self.command
        if cmd in {"translate", "improve"}:
            n = int(self.metrics.get("written", self.counts.get("written", 0)))
            if n > 0 and "keys_per_s" not in self.metrics:
                self.metrics["keys_per_s"] = round(n / self.wall_s, 4)
        elif cmd in {"review", "rescore"}:
            n = int(
                self.metrics.get("processed", self.counts.get("processed", 0))
                or self.metrics.get("updated", self.counts.get("updated", 0))
            )
            if n > 0 and "items_per_s" not in self.metrics:
                self.metrics["items_per_s"] = round(n / self.wall_s, 4)

    def tq_metric_fields(self) -> dict[str, Any]:
        """Structured summary for the final ``TQ_METRIC`` stdout line."""
        done = (
            self.metrics.get("written")
            or self.metrics.get("processed")
            or self.metrics.get("updated")
            or self.counts.get("written")
            or self.counts.get("processed")
            or self.counts.get("updated")
            or 0
        )
        total = (
            self.metrics.get("total")
            or self.counts.get("work")
            or self.counts.get("total")
            or done
        )
        fields: dict[str, Any] = {
            "command": self.command,
            "run_id": self.run_id,
            "done": done,
            "total": total,
        }
        if self.wall_s is not None:
            fields["wall_s"] = self.wall_s
        for key in ("keys_per_s", "items_per_s", "defer_scoring", "phase_a_s", "phase_b_s"):
            if key in self.metrics:
                fields[key] = self.metrics[key]
        if self.model:
            fields["model"] = self.model
        return fields

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, state_root: Path) -> Path:
        """Atomically write ``{state_root}/_runs/{run_id}.json``."""
        directory = Path(state_root) / "_runs"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run_id}.json"
        payload = self.to_dict()
        payload.pop("_t0", None)
        atomic_write_text(
            path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        _prune_runs(directory, keep=200)
        return path


def _runs_dir(state_root: Path) -> Path:
    return Path(state_root) / "_runs"


def _prune_runs(directory: Path, *, keep: int = 200) -> None:
    """Drop the oldest run files once more than ``keep`` exist."""
    files = [path for path in directory.glob("*.json") if path.is_file()]
    extra = len(files) - keep
    if extra <= 0:
        return

    def _age_key(path: Path) -> tuple[str, float]:
        started = ""
        try:
            data = read_json(path)
            if isinstance(data, dict):
                started = str(data.get("started_at") or "")
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            started = ""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        # Prefer started_at when present; fall back to mtime for ties/legacy.
        return (started or f"~{mtime:.6f}", mtime)

    files.sort(key=_age_key)
    for path in files[:extra]:
        try:
            path.unlink()
        except OSError:
            continue


def load_run_record(path: Path) -> dict[str, Any]:
    """Load one run JSON; tolerate legacy manifests without speed fields."""
    data = read_json(path)
    data.setdefault("metrics", {})
    data.setdefault("counts", {})
    return data


def latest_run_record(state_root: Path) -> dict[str, Any] | None:
    """Newest run JSON only — avoids loading every ``_runs/*.json`` for a timestamp."""
    directory = _runs_dir(state_root)
    if not directory.is_dir():
        return None
    newest: Path | None = None
    newest_mtime = -1.0
    try:
        for path in directory.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest = path
    except OSError:
        return None
    if newest is None:
        return None
    try:
        return load_run_record(newest)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def iter_run_records(
    state_root: Path,
    *,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Load all run records newest-first."""
    directory = _runs_dir(state_root)
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            row = load_run_record(path)
        except (OSError, json.JSONDecodeError):
            continue
        started = row.get("started_at") or ""
        if since and started < since:
            continue
        row["_path"] = str(path)
        records.append(row)
    return records
