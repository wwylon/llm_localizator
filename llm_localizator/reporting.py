"""Flushed stdout progress for taskqueue workers.

The queue parses ``(N%)`` on stdout (see taskqueue task_standards). Lines must
reach the log immediately — never rely on block-buffered ``print`` alone.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

Reporter = Callable[[str], None]


def report(msg: str) -> None:
    print(msg, flush=True)


def progress_line(done: int, total: int, label: str = "") -> str:
    pct = round(done / total * 100, 1) if total else (0.0 if not done else 100.0)
    if label:
        return f"[{done}/{total}] {label} ({pct}%)"
    return f"({pct}%)"


def report_progress(done: int, total: int, label: str = "") -> None:
    report(progress_line(done, total, label))


def report_metric(**fields: object) -> None:
    if fields:
        report(f"TQ_METRIC {json.dumps(fields, ensure_ascii=False)}")


def report_run_summary(manifest) -> None:
    """Emit the final structured metric line for a completed run."""
    fields = manifest.tq_metric_fields()
    if fields:
        report_metric(**fields)


@contextmanager
def log_heartbeat(
    label: str,
    *,
    interval_s: float = 30.0,
    reporter: Reporter = report,
) -> Iterator[None]:
    """Emit a keepalive line every *interval_s* while the wrapped block runs.

    Long LLM calls can sit silent for minutes; taskqueue treats ~60s without a
    log line as a hung task. Heartbeats prove the worker is alive.
    """
    stop = threading.Event()

    def _tick() -> None:
        while not stop.wait(interval_s):
            reporter(f"    … still {label}")

    thread = threading.Thread(target=_tick, daemon=True, name="log-heartbeat")
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)
