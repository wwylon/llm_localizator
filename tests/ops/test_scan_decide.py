"""scan-decide, apply mode and the decision store (ADR-55)."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog.review_queue import STATUS_DONE, open_review_queue
from llm_localizator.catalog.scan_decisions import ScanDecisions, collection_id, hit_id
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.scan_decide import REQUEST_REASON, apply_request_ticket
from llm_localizator.projects.config import ConfigError
from tests.conftest import setup_project

PAGE = "<button>Sign in now</button>\n<button>Create your account</button>\n"


@pytest.fixture
def scan_cfg(project_root, make_config):
    setup_project(project_root, {"greeting": "Hello"}, existing={"greeting": "Czesc"})
    app = project_root / "app"
    app.mkdir()
    (app / "Page.tsx").write_text(PAGE, encoding="utf-8")
    return project_root, lambda **kw: make_config(
        project_root, scan_adapter="next-intl", scan_src_dirs=["app"], **kw,
    )


def _hits(cfg, **body):
    out = dispatch_op(cfg, "agent-hardcoded", {"format": "json", **body}, actor_role="Admin")
    return out["data"]["hits"]


def _source(root):
    return json.loads((root / "messages" / "en" / "app.json").read_text(encoding="utf-8"))


def test_hit_id_ignores_line_and_whitespace() -> None:
    assert hit_id("app/Page.tsx", "Sign in  now") == hit_id("app\\Page.tsx", "Sign in now")
    assert hit_id("app/Page.tsx", "Sign in now") != hit_id("app/Other.tsx", "Sign in now")
    assert collection_id("messages", "a") != collection_id("messages", "b")


def test_store_never_demotes_an_applied_item(tmp_path) -> None:
    store = ScanDecisions(tmp_path / "d.json")
    store.decide("x", "accepted", by="ann", text="T")
    store.decide("x", "applied", by="ann")
    store.decide("x", "ignored", by="bob")
    assert store.status_of("x") == "applied"
    assert store.summary({"x", "y"}) == {"accepted": 0, "ignored": 0, "applied": 1, "pending": 1, "orphaned": 0}


def test_hits_carry_an_id_and_no_decision(scan_cfg) -> None:
    _, make = scan_cfg
    hits = _hits(make())
    assert hits and all(h["id"] and h["decision"] is None for h in hits)


def test_ignore_hides_the_hit_until_show_ignored(scan_cfg) -> None:
    _, make = scan_cfg
    cfg = make()
    target = _hits(cfg)[0]
    out = dispatch_op(cfg, "scan-decide", {"action": "ignore", "ids": [target["id"]]}, actor_role="Admin")
    assert out["ok"] is True
    assert all(h["id"] != target["id"] for h in _hits(cfg))
    shown = _hits(cfg, show_ignored=True)
    assert [h["decision"] for h in shown if h["id"] == target["id"]] == ["ignored"]


def test_decisions_survive_a_line_move_and_refresh(scan_cfg) -> None:
    root, make = scan_cfg
    cfg = make()
    target = next(h for h in _hits(cfg) if h["text"] == "Sign in now")
    dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": [target["id"]]}, actor_role="Admin")
    (root / "app" / "Page.tsx").write_text("\n\n\n" + PAGE, encoding="utf-8")
    moved = next(h for h in _hits(cfg, refresh=True) if h["text"] == "Sign in now")
    assert moved["id"] == target["id"] and moved["line"] != target["line"]
    assert moved["decision"] == "accepted"


def test_manual_mode_records_and_apply_writes_only_accepted(scan_cfg) -> None:
    root, make = scan_cfg
    cfg = make()
    target = next(h for h in _hits(cfg) if h["text"] == "Sign in now")
    out = dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": [target["id"]]}, actor_role="Admin")
    assert out["ok"] and out["data"]["mode"] == "manual" and out["data"]["applied"] == 0
    assert "signInNow" not in _source(root)

    preview = dispatch_op(cfg, "apply", {"dry_run": True}, actor_role="Admin")
    assert preview["ok"] and "signInNow" not in _source(root)
    done = dispatch_op(cfg, "apply", {"confirm": True, "enqueue_translate": False}, actor_role="Admin")
    assert done["ok"]
    written = _source(root)
    assert written["signInNow"] == "Sign in now"
    assert "createYourAccount" not in written  # nobody accepted that one
    store = ScanDecisions.for_project(cfg)
    assert store.status_of(target["id"]) == "applied"
    assert store.get(target["id"])["key"] == "signInNow"


def test_apply_without_decisions_writes_no_source_keys(scan_cfg) -> None:
    root, make = scan_cfg
    before = _source(root)
    dispatch_op(make(), "apply", {"confirm": True, "enqueue_translate": False}, actor_role="Admin")
    assert _source(root) == before


def test_key_collision_gets_a_numeric_suffix_and_same_text_is_reused(scan_cfg) -> None:
    root, make = scan_cfg
    setup_project(root, {"greeting": "Hello", "signInNow": "Something else", "createYourAccount": "Create your account"})
    cfg = make()
    ids = [h["id"] for h in _hits(cfg)]
    dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": ids}, actor_role="Admin")
    dispatch_op(cfg, "apply", {"confirm": True, "enqueue_translate": False}, actor_role="Admin")
    written = _source(root)
    assert written["signInNow"] == "Something else"
    assert written["signInNow2"] == "Sign in now"
    assert list(written.values()).count("Create your account") == 1


def test_explicit_key_that_holds_other_text_is_refused(scan_cfg) -> None:
    root, make = scan_cfg
    setup_project(root, {"greeting": "Hello"})
    cfg = make()
    target = next(h for h in _hits(cfg) if h["text"] == "Sign in now")
    out = dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": [target["id"]], "key": "greeting"}, actor_role="Admin")
    assert out["ok"] is False and "already holds" in out["summary"]
    ok = dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": [target["id"]], "key": "signIn"}, actor_role="Admin")
    assert ok["ok"] and ScanDecisions.for_project(cfg).get(target["id"])["key"] == "signIn"


def test_bulk_select_by_confidence_and_status_counts(scan_cfg) -> None:
    _, make = scan_cfg
    cfg = make()
    hits = _hits(cfg)
    level = hits[0]["confidence"]
    out = dispatch_op(cfg, "scan-decide", {"action": "ignore", "confidence": level}, actor_role="Admin")
    assert out["ok"]
    counts = dispatch_op(cfg, "scan-decide", {"action": "status"}, actor_role="Admin")["data"]["counts"]
    assert counts["ignored"] == sum(1 for h in hits if h["confidence"] == level)
    assert counts["pending"] == len(hits) - counts["ignored"]
    reset = dispatch_op(cfg, "scan-decide", {"action": "reset", "ids": [hits[0]["id"]]}, actor_role="Admin")
    assert reset["ok"]
    assert dispatch_op(cfg, "scan-decide", {"action": "accept"}, actor_role="Admin")["ok"] is False


def test_request_mode_opens_a_ticket_and_closing_it_applies_once(scan_cfg) -> None:
    root, make = scan_cfg
    cfg = make(apply_mode="request", ownership={"*": "ann"})
    target = next(h for h in _hits(cfg) if h["text"] == "Sign in now")
    out = dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": [target["id"]]}, actor_role="Admin")
    assert out["ok"] and len(out["data"]["tickets"]) == 1
    assert "signInNow" not in _source(root)

    queue = open_review_queue(cfg)
    ticket = queue.open_tickets(cfg.source_locale)[0]
    assert ticket.reason == f"{REQUEST_REASON}:{target['id']}" and ticket.source == "Sign in now"
    assert apply_request_ticket(cfg, ticket) is None  # still open: nothing happens

    queue.set_status(cfg.source_locale, ticket.id, STATUS_DONE)
    done = [t for t in queue.list_tickets(cfg.source_locale) if t.id == ticket.id][0]
    assert apply_request_ticket(cfg, done)["written"] is True
    assert _source(root)["signInNow"] == "Sign in now"
    assert apply_request_ticket(cfg, done) is None  # second close is a no-op


def test_closing_a_ticket_through_the_web_helper_applies(scan_cfg) -> None:
    from llm_localizator.catalog.review_queue import STATUS_IN_PROGRESS
    from llm_localizator.web.review import set_ticket_status

    root, make = scan_cfg
    cfg = make(apply_mode="request")
    target = next(h for h in _hits(cfg) if h["text"] == "Sign in now")
    dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": [target["id"]]}, actor_role="Admin")
    ticket = open_review_queue(cfg).open_tickets(cfg.source_locale)[0]
    mid = set_ticket_status(
        cfg, locale=cfg.source_locale, ticket_id=ticket.id, status=STATUS_IN_PROGRESS,
    )
    assert mid["ok"]
    assert "signInNow" not in _source(root)
    res = set_ticket_status(cfg, locale=cfg.source_locale, ticket_id=ticket.id, status=STATUS_DONE)
    assert res["ok"]
    assert _source(root)["signInNow"] == "Sign in now"


def test_auto_mode_applies_at_once(scan_cfg) -> None:
    root, make = scan_cfg
    cfg = make(apply_mode="auto")
    target = next(h for h in _hits(cfg) if h["text"] == "Sign in now")
    out = dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": [target["id"]], "by": "ann"}, actor_role="Admin")
    assert out["ok"] and out["data"]["applied"] == 1
    assert _source(root)["signInNow"] == "Sign in now"
    entry = ScanDecisions.for_project(cfg).get(target["id"])
    assert entry["status"] == "applied" and entry["by"] == "ann"


def test_existing_catalogue_text_is_reused_not_duplicated(scan_cfg) -> None:
    root, make = scan_cfg
    setup_project(root, {"greeting": "Sign in now"})
    cfg = make(apply_mode="auto")
    target = next(h for h in _hits(cfg) if h["text"] == "Sign in now")
    assert target["existing_key"]
    dispatch_op(cfg, "scan-decide", {"action": "accept", "ids": [target["id"]]}, actor_role="Admin")
    assert list(_source(root).values()).count("Sign in now") == 1


def test_scan_status_reports_decision_counts(scan_cfg) -> None:
    from llm_localizator.ops.agent_hardcoded import scan_cache_status

    _, make = scan_cfg
    cfg = make()
    hits = _hits(cfg)
    dispatch_op(cfg, "scan-decide", {"action": "ignore", "ids": [hits[0]["id"]]}, actor_role="Admin")
    status = scan_cache_status(cfg)
    assert status["decisions"]["ignored"] == 1
    assert status["decisions"]["pending"] == len(hits) - 1
    assert "next" in status and isinstance(status["next"], list) and status["next"]
    assert "qaLocales" in status
    assert "enXx" in status and "lagging" in status["enXx"]


def test_scan_status_flags_lagging_en_xx(tmp_path, make_config) -> None:
    from llm_localizator.ops.agent_hardcoded import scan_cache_status

    setup_project(tmp_path, {"greeting": "Hello"})
    locales = tmp_path / "locales"
    locales.mkdir()
    (locales / "en.json").write_text(
        json.dumps({"a": "A", "b": "B"}, ensure_ascii=False), encoding="utf-8",
    )
    (locales / "en-XX.json").write_text(
        json.dumps({"a": "X"}, ensure_ascii=False), encoding="utf-8",
    )
    cfg = make_config(
        tmp_path,
        catalog_format="json-flat",
        catalog_path="locales/{locale}.json",
        scan_adapter="next-intl",
        scan_src_dirs=["app"],
        qa_locales=["en-XX"],
    )
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "Page.tsx").write_text("<button>Hi</button>\n", encoding="utf-8")
    status = scan_cache_status(cfg)
    assert status["enXx"]["lagging"] is True
    assert status["enXx"]["enKeyCount"] == 2
    assert status["enXx"]["keyCount"] == 1
    assert any("pseudo" in (row.get("cmd") or "") for row in status["next"])


def test_translator_cannot_decide_or_apply(scan_cfg) -> None:
    _, make = scan_cfg
    cfg = make()
    for op in ("scan-decide", "apply", "patch"):
        out = dispatch_op(cfg, op, {"action": "status"}, actor_role="Translator")
        assert out["exit_code"] == 77
        assert dispatch_op(cfg, op, {"action": "status", "dry_run": True}, actor_role="Developer")["exit_code"] != 77


def test_collections_can_be_accepted_and_ignored(scan_cfg) -> None:
    _, make = scan_cfg
    cfg = make()
    counts = dispatch_op(cfg, "scan-decide", {"action": "status", "kind": "collection"}, actor_role="Admin")
    assert counts["ok"]
    out = dispatch_op(cfg, "scan-decide", {"action": "accept", "kind": "collection", "all_pending": True}, actor_role="Admin")
    if counts["data"]["counts"]["pending"]:
        assert out["ok"] and "collection" in out["summary"]
    else:
        assert out["ok"] is False


def test_config_rejects_an_unknown_apply_mode(tmp_path) -> None:
    from llm_localizator.projects.config import load_config

    (tmp_path / ".llm-localize.toml").write_text(
        '[project]\nname = "x"\nsource_locale = "en"\n[apply]\nmode = "sometimes"\n', encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / ".llm-localize.toml")


def test_removed_mode_flag_is_gone() -> None:
    from llm_localizator.cli.main import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["agent-hardcoded", "demo", "--mode", "apply"])


def test_init_config_with_a_scanner_declares_manual_apply_mode(tmp_path) -> None:
    from llm_localizator.projects.config import load_config
    from llm_localizator.projects.init_layout import render_init_config

    text = render_init_config("demo", "en", "json-nested", "messages/{locale}/{namespace}.json",
                              ["pl"], "next-intl")
    assert '[apply]' in text and 'mode = "manual"' in text
    path = tmp_path / ".llm-localize.toml"
    path.write_text(text, encoding="utf-8")
    assert load_config(path).apply_mode == "manual"


def test_guide_offers_the_apply_mode_step_until_it_is_set(scan_cfg) -> None:
    from llm_localizator.ops.guide import build_guide
    from llm_localizator.ops.types import GuideRequest

    root, make = scan_cfg
    cfg = make()
    step = next(s for s in build_guide(root, cfg, GuideRequest(skip_provider=True)) if s.id == "apply-mode")
    assert step.status == "todo" and step.required is False
    cfg.config_path = root / ".llm-localize.toml"
    cfg.config_path.write_text('[apply]\nmode = "auto"\n', encoding="utf-8")
    step = next(s for s in build_guide(root, cfg, GuideRequest(skip_provider=True)) if s.id == "apply-mode")
    assert step.status == "done"
