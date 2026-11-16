"""ADR-155: a dated, ADR-linked waiver line in WAIVERS.md unlocks model writes like a fresh Winner."""

from __future__ import annotations

from datetime import date, timedelta

from llm_localizator.web.settings import _fresh_waiver


def _line(day: date, adr: str = "(ADR-155)") -> str:
    return f"# waivers\n\n- {day.isoformat()} claude-haiku-5-5: smoke pass {adr}\n"


def test_recent_waiver_counts() -> None:
    cutoff = date.today() - timedelta(days=45)
    assert _fresh_waiver(_line(date.today()), cutoff)


def test_stale_waiver_does_not() -> None:
    cutoff = date.today() - timedelta(days=45)
    assert not _fresh_waiver(_line(date.today() - timedelta(days=60)), cutoff)


def test_waiver_needs_an_adr_reference() -> None:
    cutoff = date.today() - timedelta(days=45)
    assert not _fresh_waiver(_line(date.today(), adr="(user said so)"), cutoff)


def test_prose_dates_do_not_count() -> None:
    cutoff = date.today() - timedelta(days=45)
    assert not _fresh_waiver(f"Rechecked on {date.today().isoformat()} (ADR-155).\n", cutoff)
