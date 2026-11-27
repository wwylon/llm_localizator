"""Enqueue only when ``tq`` is available; otherwise run locally."""

from __future__ import annotations

from llm_localizator.ops.queue_policy import should_enqueue


def test_never_enqueue_without_tq() -> None:
    assert should_enqueue(submit=True, inline=False, tq=False) is False
    assert should_enqueue(submit=False, inline=False, tq=False) is False
    assert should_enqueue(submit=True, inline=True, tq=False) is False


def test_prefer_queue_when_tq_present() -> None:
    assert should_enqueue(submit=False, inline=False, tq=True) is True
    assert should_enqueue(submit=True, inline=False, tq=True) is True
    assert should_enqueue(submit=True, inline=True, tq=True) is True


def test_run_alias_stays_inline_even_with_tq() -> None:
    assert should_enqueue(submit=False, inline=True, tq=True) is False


def test_dry_run_never_enqueues() -> None:
    assert should_enqueue(submit=True, inline=False, dry_run=True, tq=True) is False
