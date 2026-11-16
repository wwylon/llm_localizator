"""``[ownership]`` assigns review tickets; overdue tickets escalate once (ADR-52)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from llm_localizator.catalog.review_queue import ReviewQueue, open_review_queue
from llm_localizator.pipeline import sync as sync_module
from llm_localizator.pipeline.sync import escalate_overdue
from llm_localizator.projects import ConfigError

from ..conftest import setup_project


def _queue(tmp_path, ownership=None):
    return ReviewQueue(tmp_path / "review", ownership)


def test_new_tickets_get_the_owner_of_the_first_matching_pattern(tmp_path) -> None:
    queue = _queue(tmp_path, {"legal/**": "ana", "marketing": "bo", "*": "default"})
    assert queue.enqueue(locale="pl", namespace="legal/tos", key="a", reason="r").assignee == "ana"
    assert queue.enqueue(locale="pl", namespace="marketing", key="a", reason="r").assignee == "bo"
    assert queue.enqueue(locale="pl", namespace="app", key="a", reason="r").assignee == "default"


def test_an_explicit_assignee_wins_and_no_map_means_unassigned(tmp_path) -> None:
    owned = _queue(tmp_path, {"*": "default"})
    assert owned.enqueue(locale="pl", namespace="a", key="k", reason="r", assignee="cy").assignee == "cy"
    assert _queue(tmp_path / "x").enqueue(locale="pl", namespace="a", key="k", reason="r").assignee is None


def test_open_review_queue_reads_the_config(project_root, make_config) -> None:
    cfg = make_config(project_root, ownership={"*": "team"})
    assert open_review_queue(cfg).owner_of("app", "k") == "team"


def _age(queue: ReviewQueue, ticket_id: str, days: int) -> None:
    tickets = queue._load("pl")
    for t in tickets:
        if t.id == ticket_id:
            t.created_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    queue._rewrite("pl", tickets)


def test_overdue_tickets_escalate_once(project_root, make_config, monkeypatch) -> None:
    cfg = make_config(project_root, review_escalate_after_days=3, notify_webhook="http://x.test/h")
    queue = open_review_queue(cfg)
    old = queue.enqueue(locale="pl", namespace="app", key="old", reason="r")
    queue.enqueue(locale="pl", namespace="app", key="new", reason="r")
    _age(queue, old.id, 5)
    sent: list[dict] = []
    from llm_localizator.ops import notify

    monkeypatch.setattr(notify, "notify_webhook", lambda url, payload, **_k: sent.append(payload))

    assert escalate_overdue(cfg, ["pl"], lambda _m: None) == 1
    assert [p["key"] for p in sent] == ["old"] and sent[0]["event"] == "review-escalation"
    assert escalate_overdue(cfg, ["pl"], lambda _m: None) == 0  # once only


def test_escalation_is_off_by_default(project_root, make_config) -> None:
    cfg = make_config(project_root)
    open_review_queue(cfg).enqueue(locale="pl", namespace="app", key="k", reason="r")
    assert escalate_overdue(cfg, ["pl"], lambda _m: None) == 0


def test_sync_runs_the_escalation(project_root, make_config, make_catalog, monkeypatch) -> None:
    setup_project(project_root, {"a": "Hello"})
    cfg = make_config(project_root)
    calls: list = []
    monkeypatch.setattr(sync_module, "escalate_overdue", lambda *a: calls.append(a) or 2)
    result = sync_module.run_sync(cfg, make_catalog(cfg), report=lambda _m: None)
    assert calls and result.escalated == 2


def test_config_parses_ownership_and_rejects_bad_shapes(tmp_path) -> None:
    from llm_localizator.projects.config import load_config

    def load(extra: str):
        path = tmp_path / ".llm-localize.toml"
        path.write_text(
            '[project]\nname = "t"\nsource_locale = "en"\n[locales]\ntargets = ["pl"]\n' + extra,
            encoding="utf-8",
        )
        return load_config(path)

    cfg = load('[ownership]\n"legal/**" = "ana"\n[review]\nescalate_after_days = 3\n')
    assert cfg.ownership == {"legal/**": "ana"} and cfg.review_escalate_after_days == 3
    with pytest.raises(ConfigError):
        load("[ownership]\nx = 1\n")
    with pytest.raises(ConfigError):
        load("[review]\nbogus = 1\n")
