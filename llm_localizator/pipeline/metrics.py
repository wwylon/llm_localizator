"""Process metrics (ADR-52): how much human editing the machine output needs.

Everything is derived from the per-key history files, so it is read-only and only as deep as
history retention. Edit rate is per key: of the keys a machine translated in the window, the
share a person then edited. Cycle time is the gap between those two events.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..catalog.history import HistoryEvent

__all__ = ["MACHINE_TRIGGERS", "LocaleMetrics", "compute_locale_metrics", "parse_since"]

MACHINE_TRIGGERS = frozenset({"translate", "pre-translate", "improve"})
HUMAN_TRIGGER = "web-edit"
_SINCE = re.compile(r"^(\d+)\s*([hdw])$")
_UNITS = {"h": "hours", "d": "days", "w": "weeks"}


def parse_since(value: str | None, now: datetime) -> datetime | None:
    """``30d`` / ``12h`` / ``2w`` relative to ``now``, or an ISO date; ``None`` for no bound."""
    if not value:
        return None
    match = _SINCE.match(value.strip().lower())
    if match:
        return now - timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})
    parsed = _when(value)
    if parsed is None:
        raise ValueError(f"--since must look like 30d, 12h, 2w or an ISO date, got {value!r}")
    return parsed


def _when(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


@dataclass
class LocaleMetrics:
    locale: str
    machine_keys: int = 0
    edited_keys: int = 0
    cycle_hours: list[float] | None = None
    coverage: list[dict] | None = None
    weekly: list[dict] | None = None

    @property
    def edit_rate(self) -> float | None:
        return round(self.edited_keys / self.machine_keys, 4) if self.machine_keys else None

    def to_dict(self) -> dict:
        hours = self.cycle_hours or []
        return {
            "locale": self.locale,
            "machineKeys": self.machine_keys,
            "editedKeys": self.edited_keys,
            "editRate": self.edit_rate,
            "cycleHoursMean": round(statistics.fmean(hours), 2) if hours else None,
            "cycleHoursMedian": round(statistics.median(hours), 2) if hours else None,
            "coverageTrend": self.coverage or [],
            "editRateWeekly": self.weekly or [],
        }


def compute_locale_metrics(
    locale: str,
    events: list[HistoryEvent],
    *,
    total_keys: int,
    now: datetime,
    since: datetime | None = None,
    trend_days: int = 90,
) -> LocaleMetrics:
    """Metrics for one locale from its history events (any order)."""
    per_key: dict[tuple[str, str], list[tuple[datetime, HistoryEvent]]] = {}
    for event in events:
        moment = _when(event.ts)
        if moment is not None:
            per_key.setdefault((event.namespace, event.key), []).append((moment, event))

    out = LocaleMetrics(locale, cycle_hours=[])
    first_seen: list[datetime] = []
    outcomes: list[tuple[datetime, bool]] = []
    for rows in per_key.values():
        rows.sort(key=lambda row: row[0])
        first_seen.append(rows[0][0])
        machine = next(
            (m for m, e in rows if e.trigger in MACHINE_TRIGGERS and (since is None or m >= since)),
            None,
        )
        if machine is None:
            continue
        out.machine_keys += 1
        edit = next(
            (m for m, e in rows if m > machine and e.trigger == HUMAN_TRIGGER and e.status == "human"),
            None,
        )
        outcomes.append((machine, edit is not None))
        if edit is not None:
            out.edited_keys += 1
            out.cycle_hours.append((edit - machine).total_seconds() / 3600.0)

    out.coverage = _coverage_trend(first_seen, total_keys, now, trend_days)
    out.weekly = _weekly_edit_rate(outcomes, now)
    return out


def _weekly_edit_rate(outcomes: list[tuple[datetime, bool]], now: datetime, weeks: int = 12) -> list[dict]:
    """Per week: of keys first machine-translated that week, the share a person later edited."""
    points: list[dict] = []
    for step in range(weeks - 1, -1, -1):
        end = now - timedelta(weeks=step)
        start = end - timedelta(weeks=1)
        batch = [edited for moment, edited in outcomes if start < moment <= end]
        points.append({
            "weekEnding": end.date().isoformat(),
            "machineKeys": len(batch),
            "editRate": round(sum(batch) / len(batch), 4) if batch else None,
        })
    return points


def _coverage_trend(first_seen: list[datetime], total: int, now: datetime, days: int) -> list[dict]:
    """Share of the current source keys that had a value by each week's end (approximate)."""
    if not total:
        return []
    points: list[dict] = []
    weeks = max(1, days // 7)
    for step in range(weeks, -1, -1):
        edge = now - timedelta(weeks=step)
        have = sum(1 for moment in first_seen if moment <= edge)
        points.append({
            "weekEnding": edge.date().isoformat(),
            "coverage": round(min(1.0, have / total), 4),
        })
    return points
