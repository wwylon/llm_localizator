"""Every inline LLM op needs confirm; dry runs and queued runs do not (M0, audit ops #14)."""

from __future__ import annotations

import pytest

from llm_localizator.ops import dispatch_cmds


@pytest.fixture(autouse=True)
def _no_taskqueue(monkeypatch):
    from llm_localizator.projects import taskqueue

    monkeypatch.setattr(taskqueue, "tq_available", lambda: False)


@pytest.mark.parametrize("cmd", ["review", "rescore", "documents", "bakeoff"])
def test_inline_llm_op_without_confirm_is_refused(cmd) -> None:
    out = dispatch_cmds._spend_gate(cmd, {})
    assert out and out["ok"] is False and "confirm" in out["error"]


def test_confirm_dry_run_and_queue_pass(monkeypatch) -> None:
    assert dispatch_cmds._spend_gate("rescore", {"confirm": True}) is None
    assert dispatch_cmds._spend_gate("rescore", {"dry_run": True}) is None
    from llm_localizator.projects import taskqueue

    monkeypatch.setattr(taskqueue, "tq_available", lambda: True)
    assert dispatch_cmds._spend_gate("rescore", {"submit": True}) is None


def test_hardcoded_llm_judge_has_no_queue_escape(monkeypatch) -> None:
    from llm_localizator.projects import taskqueue

    monkeypatch.setattr(taskqueue, "tq_available", lambda: True)
    assert dispatch_cmds._spend_gate("agent-hardcoded --llm", {"submit": True}, queueable=False)
