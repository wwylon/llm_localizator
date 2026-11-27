"""ADR-15 prefers the queue; the ``run-`` aliases must still run in this process."""

from __future__ import annotations

import pytest

from llm_localizator.ops.dispatch import dispatch_op

from tests.conftest import setup_project


@pytest.fixture
def queue_present(monkeypatch):
    """A machine where ``tq`` is installed, and a trap on the submit path.

    Patch both the spend-gate probe (``projects.taskqueue``) and the translate
    module's own import — dispatch checks the former before calling ``op_translate``.
    """
    submitted: list[str] = []

    def fake_submit(cfg, req):
        submitted.append("submitted")
        from llm_localizator.ops.types import OpResult

        return OpResult(ok=True, exit_code=0, command="translate", summary="queued")

    monkeypatch.setattr("llm_localizator.projects.taskqueue.tq_available", lambda: True)
    monkeypatch.setattr("llm_localizator.ops.translate.tq_available", lambda: True)
    monkeypatch.setattr("llm_localizator.ops.translate._submit", fake_submit)
    return submitted


def test_translate_still_prefers_the_queue(project_root, make_config, queue_present) -> None:
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root)
    out = dispatch_op(cfg, "translate", {"locales": ["pl"]}, actor_role="Admin")
    assert out["summary"] == "queued"
    assert queue_present == ["submitted"]


def test_run_translate_runs_in_process_even_when_tq_exists(
    project_root, make_config, queue_present,
) -> None:
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root)
    out = dispatch_op(cfg, "run-translate", {"locales": ["pl"]}, actor_role="Admin")
    assert queue_present == []
    assert out["ok"] is True
    assert out["summary"].startswith("written 1/1")
