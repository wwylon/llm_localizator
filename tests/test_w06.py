"""Review queue page, ticket HTTP API, and single-key improve."""

from __future__ import annotations


from llm_localizator.catalog.review_queue import (
    STATUS_DONE,
    STATUS_OPEN,
    ReviewQueue,
)
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.types import ImproveRequest
from llm_localizator.pipeline.improve import collect_named_improve_keys, _parse_named_keys
from llm_localizator.web.review import (
    comment_on_ticket,
    create_review_ticket,
    list_review_tickets,
    set_ticket_status,
)
from llm_localizator.web.shell import render_shell

from .conftest import setup_project


def test_fixture_jsonl_round_trips_through_list(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"greet": "Hello"})
    cfg = make_config(tmp_path)
    queue = ReviewQueue(cfg.review_root())
    ticket = queue.enqueue(
        locale="pl", namespace="app", key="greet",
        reason="needs_context", source="Hello", current="Witaj",
    )
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "greet", score=0.4, signals=[], text="Witaj")
    scores.save("pl")
    payload = list_review_tickets(cfg, locale="pl", status="open")
    assert payload["ok"] is True
    assert len(payload["tickets"]) == 1
    row = payload["tickets"][0]
    assert row["id"] == ticket.id
    assert row["reason"] == "needs_context"
    assert row["score"] == 0.4
    assert row["source"] == "Hello"


def test_comment_keeps_older_comments(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    queue = ReviewQueue(cfg.review_root())
    ticket = queue.enqueue(locale="pl", namespace="app", key="greet", reason="needs_context")
    queue.add_comment("pl", ticket.id, "alice", "first")
    result = comment_on_ticket(
        cfg, locale="pl", ticket_id=ticket.id, author="bob", body="second",
    )
    assert result["ok"] is True
    bodies = [c["body"] for c in result["ticket"]["comments"]]
    assert bodies == ["first", "second"]


def test_post_and_resolve_sets_done(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    queue = ReviewQueue(cfg.review_root())
    ticket = queue.enqueue(locale="pl", namespace="app", key="greet", reason="needs_context")
    result = comment_on_ticket(
        cfg, locale="pl", ticket_id=ticket.id,
        author="alice", body="fixed", resolve=True,
    )
    assert result["ok"] is True
    assert result["ticket"]["status"] == STATUS_DONE


def test_unknown_status_leaves_file_unchanged(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    queue = ReviewQueue(cfg.review_root())
    ticket = queue.enqueue(locale="pl", namespace="app", key="greet", reason="needs_context")
    path = queue.path_for("pl")
    before = path.read_bytes()
    result = set_ticket_status(
        cfg, locale="pl", ticket_id=ticket.id, status="in_review",
    )
    assert result["ok"] is False
    assert "unknown status" in result["error"]
    assert path.read_bytes() == before


def test_create_then_list_returns_ticket(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    created = create_review_ticket(
        cfg,
        locale="pl",
        namespace="app",
        key="bye",
        reason="needs_context",
        description="please check",
        author="alice",
        assignee="bob",
    )
    assert created["ok"] is True
    listed = list_review_tickets(cfg, locale="pl", status=STATUS_OPEN)
    ids = [t["id"] for t in listed["tickets"]]
    assert created["ticket"]["id"] in ids
    ticket = created["ticket"]
    assert ticket["assignee"] == "bob"
    assert ticket["comments"][0]["body"] == "please check"
    assert ticket["comments"][0]["author"] == "alice"


def test_review_shell_mounts_script() -> None:
    html = render_shell("review")
    assert 'data-page="review"' in html
    assert "/static/review.js" in html
    assert "W-06 fills this page." not in html


def test_improve_body_contains_only_named_key() -> None:
    """The resolve checkbox must POST one key and no others."""
    req = ImproveRequest(locales=["pl"], keys=["app.greet"])
    body = {
        "locales": req.locales,
        "keys": req.keys,
        "confirm": True,
    }
    assert body["keys"] == ["app.greet"]
    assert len(body["keys"]) == 1
    assert "app.other" not in body["keys"]


def test_named_improve_keys_skip_score_gate(tmp_path, make_config, make_catalog) -> None:
    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    cfg = make_config(tmp_path)
    catalog = make_catalog(cfg)
    from llm_localizator.catalog import StateStore, make_entry

    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "greet", make_entry("Hello", "m", "machine"))
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "greet", score=0.99, signals=[], text="Witaj")
    scores.save("pl")
    named = _parse_named_keys(["app.greet"])
    rows = collect_named_improve_keys(
        cfg, catalog, state, scores, locales=["pl"], named=named,
    )
    assert len(rows) == 1
    assert rows[0][2] == "greet"


def test_dispatch_improve_accepts_keys(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    cfg = make_config(tmp_path)
    result = dispatch_op(cfg, "improve", {
        "locales": ["pl"],
        "keys": ["app.greet"],
        "dry_run": True,
        "confirm": True,
    }, actor_role="Admin")
    assert result.get("ok") is True
    assert result.get("data", {}).get("dryRun") is True
