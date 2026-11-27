"""Explicit inline LLM ops need confirm; dry runs, queued runs, and no-tq default do not."""

from __future__ import annotations

import pytest

from llm_localizator.ops import dispatch_cmds


@pytest.fixture(autouse=True)
def _no_taskqueue(monkeypatch):
    from llm_localizator.projects import taskqueue

    monkeypatch.setattr(taskqueue, "tq_available", lambda: False)


@pytest.mark.parametrize("cmd", ["review", "rescore", "documents", "bakeoff", "translate"])
def test_explicit_inline_without_confirm_is_refused(cmd) -> None:
    out = dispatch_cmds._spend_gate(cmd, {"inline": True})
    assert out and out["ok"] is False and "confirm" in out["error"]


@pytest.mark.parametrize("cmd", ["review", "rescore", "documents", "bakeoff", "translate"])
def test_no_tq_default_runs_without_confirm(cmd) -> None:
    """Without taskqueue the operator path is local — same as the CLI."""
    assert dispatch_cmds._spend_gate(cmd, {}) is None


def test_confirm_dry_run_and_queue_pass(monkeypatch) -> None:
    assert dispatch_cmds._spend_gate("rescore", {"confirm": True}) is None
    assert dispatch_cmds._spend_gate("rescore", {"dry_run": True}) is None
    from llm_localizator.projects import taskqueue

    monkeypatch.setattr(taskqueue, "tq_available", lambda: True)
    assert dispatch_cmds._spend_gate("rescore", {"submit": True}) is None
    assert dispatch_cmds._spend_gate("rescore", {"inline": True}) is not None


def test_hardcoded_llm_judge_has_no_queue_escape(monkeypatch) -> None:
    from llm_localizator.projects import taskqueue

    monkeypatch.setattr(taskqueue, "tq_available", lambda: True)
    assert dispatch_cmds._spend_gate("agent-hardcoded --llm", {"submit": True}, queueable=False)
