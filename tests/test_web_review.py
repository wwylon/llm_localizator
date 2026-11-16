"""Review page payload: display ids, counts, status events, old-format files (ADR-66)."""

from __future__ import annotations

import json

from llm_localizator.catalog.review_queue import open_review_queue
from llm_localizator.web.review import (
    create_review_ticket,
    list_review_tickets,
    review_counts,
    set_ticket_status,
)


def _cfg(tmp_path, make_config):
    return make_config(tmp_path)


def test_payload_has_display_id_type_and_comment_count(tmp_path, make_config) -> None:
    cfg = _cfg(tmp_path, make_config)
    first = create_review_ticket(cfg, locale="pl", namespace="app", key="a", reason="low_score",
                                 title="Bad word", description="see this", author="ann")
    second = create_review_ticket(cfg, locale="pl", namespace="app", key="b", reason="question")
    assert first["ticket"]["display_id"] == "RQ-001"
    assert second["ticket"]["display_id"] == "RQ-002"
    assert first["ticket"]["type"] == "low_score"
    assert first["ticket"]["comment_count"] == 1
    assert first["ticket"]["title"] == "Bad word"
    assert first["ticket"]["opened_by"] == "ann"
    listed = list_review_tickets(cfg, locale="pl")
    assert [t["key"] for t in listed["tickets"]] == ["b", "a"]  # newest first


def test_status_change_records_event_and_counts(tmp_path, make_config) -> None:
    cfg = _cfg(tmp_path, make_config)
    tid = create_review_ticket(cfg, locale="pl", namespace="app", key="a", reason="r")["ticket"]["id"]
    out = set_ticket_status(cfg, locale="pl", ticket_id=tid, status="in_progress",
                            assignee="bob", actor="ann")
    assert out["ok"], out
    kinds = [(e["kind"], e["actor"]) for e in out["ticket"]["events"]]
    assert ("status", "ann") in kinds and ("assignee", "ann") in kinds
    counts = review_counts(cfg, ["pl"])
    assert counts["active"] == 1 and counts["counts"]["in_progress"] == 1
    set_ticket_status(cfg, locale="pl", ticket_id=tid, status="done", actor="ann")
    assert review_counts(cfg, ["pl"])["active"] == 0
    assert list_review_tickets(cfg, locale="pl")["counts"]["done"] == 1


def test_old_format_ticket_file_still_loads(tmp_path, make_config) -> None:
    cfg = _cfg(tmp_path, make_config)
    queue = open_review_queue(cfg)
    path = queue.path_for("pl")
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {"id": "old1", "locale": "pl", "namespace": "n", "key": "k", "reason": "x",
           "status": "open", "assignee": None, "comments": [],
           "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
    path.write_text(json.dumps(old) + "\n", encoding="utf-8")
    listed = list_review_tickets(cfg, locale="pl")
    row = listed["tickets"][0]
    assert row["display_id"] == "RQ-001" and row["events"] == [] and row["opened_by"] == "system"
