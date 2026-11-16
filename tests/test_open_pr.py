"""C-015 and C-025: PR for catalogue changes with Co-authored-by trailers (ADR-101). Fake runner only."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from llm_localizator.catalog.history import HistoryEvent, HistoryStore
from llm_localizator.ops.open_pr import op_open_pr
from llm_localizator.ops.types import OpenPrRequest
from llm_localizator.projects.config import ConfigError, load_config
from llm_localizator.projects.git_host import RunResult, coauthor_trailers


def _cfg(tmp_path, monkeypatch, host="[git_host]\nenabled = true\n"):
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))
    (tmp_path / ".llm-localize.toml").write_text("\n".join([
        "[project]", 'name = "demo"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "m/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "", host,
    ]), encoding="utf-8")
    return load_config(tmp_path / ".llm-localize.toml")


def _event(name=None, model="m1", provider="ollama", ts="2026-10-20T10:00:00Z"):
    return HistoryEvent(
        ts=ts, namespace="app", key="k", prev=None, next="x", model=model, status="ok",
        src_sha="s", trigger="t", provider=provider, edited_by_name=name,
    )


class Fake:
    def __init__(self, status=" M m/de/app.json\n", fail=None):
        self.calls, self.status, self.fail = [], status, fail

    def __call__(self, argv, cwd):
        self.calls.append(argv)
        if self.fail and argv[:2] == self.fail:
            return RunResult(1, "", "boom")
        if argv[:2] == ["git", "status"]:
            return RunResult(0, self.status)
        if argv[:2] == ["git", "log"]:
            return RunResult(0, "2026-10-01T00:00:00+00:00\n")
        if argv[:3] == ["gh", "pr", "create"]:
            return RunResult(0, "https://example.test/pr/7\n")
        if argv[:3] == ["gh", "pr", "view"]:
            return RunResult(0, json.dumps({"number": 7, "state": "OPEN", "url": "u", "title": "t"}))
        return RunResult(0)


def test_default_is_off_and_config_is_strict(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, host="")
    assert cfg.git_host["enabled"] is False
    res = op_open_pr(cfg, OpenPrRequest(), Fake())
    assert not res.ok and "off" in res.summary
    with pytest.raises(ConfigError):
        _cfg(tmp_path, monkeypatch, "[git_host]\nkind = \"gitlab\"\n")
    with pytest.raises(ConfigError):
        _cfg(tmp_path, monkeypatch, "[git_host]\nbase = \"--evil\"\n")


def test_plan_writes_nothing_and_lists_files(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    fake = Fake()
    res = op_open_pr(cfg, OpenPrRequest(), fake)
    assert res.ok and res.data["files"] == ["m/de/app.json"]
    assert res.data["branch"].startswith("l10n/")
    assert all(c[:2] in (["git", "status"], ["git", "log"]) for c in fake.calls)
    assert fake.calls[0][-1] == "m"  # only the catalogue directory is asked about


def test_open_needs_confirm_then_runs_the_steps_in_order(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    assert not op_open_pr(cfg, OpenPrRequest(action="open"), Fake()).ok
    fake = Fake()
    res = op_open_pr(cfg, OpenPrRequest(action="open", confirm=True), fake)
    assert res.ok and res.data["url"] == "https://example.test/pr/7"
    verbs = [c[1] if c[0] == "git" else "gh" for c in fake.calls]
    assert verbs == ["status", "log", "checkout", "add", "commit", "push", "gh"]
    add = next(c for c in fake.calls if c[:2] == ["git", "add"])
    assert add[-2:] == ["--", "m/de/app.json"]  # by path, never -A


def test_failure_stops_and_nothing_to_send_is_refused(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    fake = Fake(fail=["git", "push"])
    res = op_open_pr(cfg, OpenPrRequest(action="open", confirm=True), fake)
    assert not res.ok and "boom" in res.summary
    assert not any(c[0] == "gh" for c in fake.calls)
    res = op_open_pr(cfg, OpenPrRequest(action="open", confirm=True), Fake(status=""))
    assert not res.ok and "no catalogue changes" in res.summary


def test_status_validates_the_branch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    assert op_open_pr(cfg, OpenPrRequest(action="status", branch="l10n/x"), Fake()).data["state"] == "OPEN"
    assert not op_open_pr(cfg, OpenPrRequest(action="status", branch="--web"), Fake()).ok


def test_trailers_dedupe_skip_humans_without_names_and_old_edits(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    store = HistoryStore(cfg.history_root())
    for ev in (
        _event("Ann Lee", model="human", provider="human"), _event("Ann Lee"),
        _event(None, model="qwen3:8b"), _event(None, model="human", provider="human"),
        _event(None, model="old-model", ts="2026-09-01T00:00:00Z"),
        _event(None, model="imp", provider="import"),
    ):
        store.append("de", ev)
    since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert coauthor_trailers(cfg, since) == [
        "Co-authored-by: Ann Lee <ann.lee@llm-localizator.invalid>",
        "Co-authored-by: qwen3:8b <qwen3.8b@llm-localizator.invalid>",
    ]
    plan = op_open_pr(cfg, OpenPrRequest(), Fake()).data
    assert plan["body"].endswith("<qwen3.8b@llm-localizator.invalid>")
