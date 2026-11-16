"""Source-change log, `watch`, and the supervisor named in an escalation (ADR-52)."""

from __future__ import annotations

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.catalog.review_queue import open_review_queue
from llm_localizator.catalog.source_history import SourceHistory
from llm_localizator.ops import watch as watch_module
from llm_localizator.ops.push_strings import PushStringsRequest, op_push_strings
from llm_localizator.pipeline import sync as sync_module
from llm_localizator.pipeline.sync import run_sync, supervisor_for
from llm_localizator.projects.accounts import AccountStore

from ..conftest import setup_project, write_json

quiet = lambda _m: None  # noqa: E731


def _stale_project(project_root, make_config):
    setup_project(project_root, {"a": "Sign in to your account"}, existing={"a": "Zaloguj"})
    cfg = make_config(project_root)
    state = StateStore(cfg.state_root())
    state.record("pl", "app", "a", make_entry("Sign in", "m"))
    state.save("pl")
    return cfg


def test_sync_logs_a_source_change_once(project_root, make_config, make_catalog) -> None:
    cfg = _stale_project(project_root, make_config)
    for _ in range(2):
        run_sync(cfg, make_catalog(cfg), report=quiet)
    rows = SourceHistory(cfg.state_root())._rows()
    assert len(rows) == 1
    assert rows[0]["trigger"] == "source-changed"
    assert (rows[0]["prev_src"], rows[0]["next_src"]) == ("Sign in", "Sign in to your account")
    assert SourceHistory(cfg.state_root()).latest("app", "a")["next_src"].startswith("Sign in to")


def test_dry_run_logs_nothing(project_root, make_config, make_catalog) -> None:
    cfg = _stale_project(project_root, make_config)
    run_sync(cfg, make_catalog(cfg), dry_run=True, report=quiet)
    assert SourceHistory(cfg.state_root()).latest("app", "a") is None


def test_a_second_change_is_a_second_line(tmp_path) -> None:
    log = SourceHistory(tmp_path)
    assert log.record_changes([("app", "a", "One", "Two")]) == 1
    assert log.record_changes([("app", "a", "One", "Two")]) == 0
    assert log.record_changes([("app", "a", "Two", "Three")]) == 1
    assert log.record_changes([("app", "b", "", "New")]) == 0  # a new key is not a change
    assert log.latest("app", "a")["next_src"] == "Three"


def test_push_strings_logs_the_update(project_root, make_config) -> None:
    setup_project(project_root, {"a": "Sign in"})
    cfg = make_config(project_root)
    result = op_push_strings(cfg, PushStringsRequest(namespace="app", strings={"a": "Sign in now"}))
    assert result.ok
    row = SourceHistory(cfg.state_root()).latest("app", "a")
    assert (row["prev_src"], row["next_src"]) == ("Sign in", "Sign in now")


def test_watch_syncs_once_and_again_after_a_change(project_root, make_config, monkeypatch) -> None:
    setup_project(project_root, {"a": "Hello"})
    cfg = make_config(project_root)
    runs: list[int] = []
    monkeypatch.setattr(watch_module, "run_sync", lambda *a, **k: runs.append(1))
    ticks = iter(range(10))

    def sleep(_seconds: float) -> None:
        if next(ticks) == 1:  # the second poll sees a changed file
            write_json(project_root / "messages" / "en" / "app.json", {"a": "Hello there"})

    lines: list[str] = []
    assert watch_module.run_watch(cfg, interval=1, max_cycles=3, sleep=sleep, report=lines.append) == 0
    assert len(runs) == 2  # once at start, once after the change; quiet polls do nothing
    assert any("changed app.json" in line for line in lines)


def test_supervisor_lookup_respects_locale_chips(project_root, make_config) -> None:
    cfg = make_config(project_root)
    store = AccountStore(cfg.state_root())
    store.register("admin1", "password123")
    other = store.register("sup-de", "password123")["user"]["id"]
    mine = store.register("sup-pl", "password123")["user"]["id"]
    store.set_role(other, role="Supervisor", locales=["de"])
    store.set_role(mine, role="Supervisor", locales=["pl"])
    assert supervisor_for(cfg, "pl") == "sup-pl"
    assert supervisor_for(cfg, "de") == "sup-de"
    assert supervisor_for(cfg, "fr") is None


def test_escalation_names_the_supervisor(project_root, make_config, monkeypatch) -> None:
    cfg = make_config(project_root, review_escalate_after_days=1, notify_webhook="http://x.test/h")
    store = AccountStore(cfg.state_root())
    store.register("admin1", "password123")
    sup = store.register("boss", "password123")["user"]["id"]
    store.set_role(sup, role="Supervisor")
    queue = open_review_queue(cfg)
    ticket = queue.enqueue(locale="pl", namespace="app", key="k", reason="r")
    tickets = queue._load("pl")
    tickets[0].created_at = "2020-01-01T00:00:00Z"
    queue._rewrite("pl", tickets)
    sent: list[dict] = []
    from llm_localizator.ops import notify

    monkeypatch.setattr(notify, "notify_webhook", lambda url, payload, **_k: sent.append(payload))
    assert sync_module.escalate_overdue(cfg, ["pl"], quiet) == 1
    assert sent[0]["supervisor"] == "boss" and sent[0]["ticket"] == ticket.id
