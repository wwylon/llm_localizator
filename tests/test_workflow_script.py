"""ADR-63 — block scripts: validation, interpreter, resumable runs, persistence."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog.review_queue import ReviewQueue
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.state import StateStore, make_entry
from llm_localizator.core.workflow_rules import (
    MAX_BLOCKS,
    MAX_DEPTH,
    legacy_script,
    normalize_script,
    script_warnings,
    canonical_rules,
)
from llm_localizator.ops import workflow_run as wr
from llm_localizator.ops.workflow import WorkflowRequest, op_workflow_run
from llm_localizator.projects.config import load_config
from llm_localizator.web.workflow_config import get_named_workflow, save_workflows

from .conftest import setup_project
from .test_w10 import _toml

SCORES = {"hi": 0.90, "mid": 0.70, "lo": 0.40}


@pytest.fixture(autouse=True)
def _no_taskqueue(monkeypatch):
    monkeypatch.setattr(wr, "tq_available", lambda: False)


def _project(tmp_path):
    setup_project(tmp_path, {"hi": "High", "mid": "Mid", "lo": "Low"},
                  existing={"hi": "H", "mid": "M", "lo": "L"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    store = StateStore(cfg.state_root())
    scores = ScoreStore(cfg.scores_root())
    for key, sc in SCORES.items():
        store.record("pl", "app", key, make_entry(key, "m", provider="ollama"))
        scores.record("pl", "app", key, score=sc, signals=[], text=key[0].upper())
    store.save("pl")
    scores.save("pl")
    return cfg


def _run(cfg, script, **kw):
    assert save_workflows(cfg, workflows={"w": {"script": script}})["ok"]
    cfg = load_config(cfg.config_path)
    req = WorkflowRequest(name="w", route_only=True, locales=["pl"], namespace="app", **kw)
    return cfg, op_workflow_run(cfg, req)


def _cond(value, op="ge"):
    return {"type": "if", "field": "score", "op": op, "value": value}


def test_validation_rejects_unknown_and_bad_cond() -> None:
    with pytest.raises(ValueError):
        normalize_script([{"type": "bogus"}])
    with pytest.raises(ValueError):
        normalize_script([{"type": "if", "field": "locale", "op": "ge", "value": 1}])


def test_hardcoded_field_is_a_valid_if_cond() -> None:
    script = normalize_script([
        {"type": "if", "field": "hardcoded", "op": "ge", "value": 1,
         "then": [{"type": "review_ticket"}], "else": [{"type": "stop"}]},
    ])
    assert script[0]["field"] == "hardcoded"


def test_findings_field_is_a_valid_if_cond() -> None:
    script = normalize_script([
        {"type": "if", "field": "findings", "op": "ge", "value": 1,
         "then": [{"type": "flag"}], "else": [{"type": "verify"}]},
    ])
    assert script[0]["field"] == "findings"


def test_validate_findings_branch_flags_only_bad_keys(tmp_path, monkeypatch) -> None:
    from llm_localizator.ops.types import OpResult

    cfg = _project(tmp_path)
    script = [
        {"type": "validate"},
        {"type": "if", "field": "findings", "op": "ge", "value": 1,
         "then": [{"type": "flag"}], "else": [{"type": "verify"}]},
    ]
    assert save_workflows(cfg, workflows={"w": {"script": script}})["ok"]
    cfg = load_config(cfg.config_path)

    def fake_validate(_cfg, _req, **_kw):
        return OpResult(
            ok=True, exit_code=0, command="validate", summary="1 finding",
            lines=[], data={"findings": [
                {"locale": "pl", "namespace": "app", "key": "lo", "check": "V1", "severity": "error"},
            ]},
        )

    monkeypatch.setattr("llm_localizator.ops.validate.op_validate", fake_validate)
    res = op_workflow_run(
        cfg, WorkflowRequest(name="w", route_only=True, locales=["pl"], namespace="app"),
    )
    assert res.ok
    assert int(res.data.get("flagged") or 0) == 1
    assert int(res.data.get("verified") or 0) == 2



def test_validation_caps() -> None:
    deep = [{"type": "stop"}]
    for _ in range(MAX_DEPTH + 1):
        deep = [{**_cond(0.5), "then": deep}]
    with pytest.raises(ValueError):
        normalize_script(deep)
    with pytest.raises(ValueError):
        normalize_script([{"type": "flag"}] * (MAX_BLOCKS + 1))


def test_warnings() -> None:
    script = normalize_script([
        {**_cond(0.5), "then": []},
        {"type": "stop"},
        {"type": "flag"},
    ])
    codes = " ".join(script_warnings(script))
    assert "score_before_rescore" in codes
    assert "empty_branch" in codes
    assert "unreachable_after_stop" in codes


def test_legacy_script_shape() -> None:
    script = legacy_script(canonical_rules(0.8, 0.55))
    assert [b["type"] for b in script[:2]] == ["translate", "rescore"]
    assert script[-1]["type"] in ("if", "review_ticket")


def test_if_else_routes_and_counts(tmp_path) -> None:
    cfg = _project(tmp_path)
    script = [{**_cond(0.8), "then": [{"type": "verify"}], "else": [{"type": "review_ticket"}]}]
    cfg, res = _run(cfg, script)
    assert res.ok
    assert res.data["verified"] == 1
    assert res.data["tickets"] == 2
    entry = StateStore(cfg.state_root()).entry("pl", "app", "hi")
    assert entry.get("verified_by") == "workflow"


def test_stop_and_order_matter(tmp_path) -> None:
    cfg = _project(tmp_path)
    # stop first: nothing acts
    cfg, res = _run(cfg, [{"type": "stop"}, {"type": "review_ticket"}])
    assert res.data["tickets"] == 0
    cfg, res = _run(cfg, [{"type": "review_ticket"}, {"type": "stop"}])
    assert res.data["tickets"] == 3


def test_terminal_removes_keys_from_flow(tmp_path) -> None:
    cfg = _project(tmp_path)
    script = [
        {**_cond(0.8), "then": [{"type": "verify"}]},
        {"type": "review_ticket"},
    ]
    cfg, res = _run(cfg, script)
    assert res.data["verified"] == 1
    # verified key is not also ticketed
    keys = {t.key for t in ReviewQueue(cfg.review_root()).list_tickets("pl")}
    assert "hi" not in keys and keys == {"mid", "lo"}


def test_nested_if(tmp_path) -> None:
    cfg = _project(tmp_path)
    inner = {**_cond(0.5), "then": [{"type": "review_ticket"}], "else": [{"type": "flag"}]}
    script = [{**_cond(0.8), "then": [{"type": "verify"}], "else": [inner]}]
    cfg, res = _run(cfg, script)
    assert res.data["verified"] == 1
    assert res.data["tickets"] == 1


def test_dry_run_has_no_side_effects(tmp_path) -> None:
    cfg = _project(tmp_path)
    script = [{"type": "verify"}]
    cfg, res = _run(cfg, script, dry_run=True)
    assert res.ok
    assert StateStore(cfg.state_root()).entry("pl", "app", "hi").get("verified_by") != "workflow"
    assert wr.latest_run(cfg, "w") is None


def test_save_round_trip_nested(tmp_path) -> None:
    cfg = _project(tmp_path)
    script = [
        {"type": "translate"},
        {**_cond(0.8), "then": [{"type": "verify"}],
         "else": [{"type": "if", "field": "locale", "op": "is", "value": "pl",
                   "then": [{"type": "flag"}, {"type": "stop"}],
                   "else": [{"type": "review_ticket"}]}]},
    ]
    assert save_workflows(cfg, workflows={"w": {"script": script}})["ok"]
    back = load_config(cfg.config_path).workflows["w"]["script"]
    assert back == normalize_script(script)
    assert get_named_workflow(load_config(cfg.config_path), "w")["script"] == back


def test_classic_shape_compacts_to_thresholds(tmp_path) -> None:
    cfg = _project(tmp_path)
    assert save_workflows(cfg, workflows={"w": {"high": 0.8, "low": 0.55}})["ok"]
    text = cfg.config_path.read_text(encoding="utf-8")
    assert "high = 0.8" in text and "script" not in text.split("[workflows.w]")[1]


def _parked(tmp_path, monkeypatch):
    cfg = _project(tmp_path)
    monkeypatch.setattr(wr, "tq_available", lambda: True)
    monkeypatch.setattr(wr._Run, "_submit_or_run",
                        lambda self, kind, keys: (True, "queued", ["t1"], {}))
    state = {"v": "pending"}
    monkeypatch.setattr(wr, "task_state", lambda ids, **k: state["v"])
    assert save_workflows(cfg, workflows={"w": {"script": [
        {"type": "rescore"}, {"type": "review_ticket"}]}})["ok"]
    cfg = load_config(cfg.config_path)
    from llm_localizator.ops.workflow import get_workflow
    spec = get_workflow(cfg, "w")
    res = wr.start_run(cfg, spec, WorkflowRequest(name="w", locales=["pl"], namespace="app"))
    return cfg, spec, res.data["runId"], state


def test_waiting_then_resume(tmp_path, monkeypatch) -> None:
    cfg, spec, rid, state = _parked(tmp_path, monkeypatch)
    assert wr.load_run(cfg, rid)["status"] == "waiting"
    assert not ReviewQueue(cfg.review_root()).list_tickets("pl")
    wr.resume_run(cfg, spec, rid)            # still pending: idempotent
    assert wr.load_run(cfg, rid)["status"] == "waiting"
    state["v"] = "done"
    wr.resume_run(cfg, spec, rid)
    assert wr.load_run(cfg, rid)["status"] == "done"
    assert len(ReviewQueue(cfg.review_root()).list_tickets("pl")) == 3
    wr.resume_run(cfg, spec, rid)            # finished: no double tickets
    assert len(ReviewQueue(cfg.review_root()).list_tickets("pl")) == 3


def test_failed_task_fails_run(tmp_path, monkeypatch) -> None:
    cfg, spec, rid, state = _parked(tmp_path, monkeypatch)
    state["v"] = "failed"
    wr.resume_run(cfg, spec, rid)
    assert wr.load_run(cfg, rid)["status"] == "failed"


def test_cancel_waiting(tmp_path, monkeypatch) -> None:
    cfg, spec, rid, state = _parked(tmp_path, monkeypatch)
    assert wr.cancel_run(cfg, rid)["status"] == "canceled"
    state["v"] = "done"
    wr.resume_run(cfg, spec, rid)
    assert wr.load_run(cfg, rid)["status"] == "canceled"


def test_cancel(tmp_path) -> None:
    cfg = _project(tmp_path)
    assert wr.cancel_run(cfg, "wf_missing") is None


def test_default_workflow_is_pinned() -> None:
    from llm_localizator.core.workflow_rules import default_script
    from llm_localizator.ops.workflow import WorkflowSpec

    s = default_script()
    assert [b["type"] for b in s] == ["translate", "rescore", "if"]
    top = s[2]
    assert (top["field"], top["op"], top["value"]) == ("score", "ge", 0.8)
    assert [b["type"] for b in top["then"]] == ["verify"]
    nxt = top["else"][0]
    assert (nxt["op"], nxt["value"]) == ("le", 0.55)
    assert [b["type"] for b in nxt["then"]] == ["improve"]
    assert [b["type"] for b in nxt["else"]] == ["review_ticket"]
    assert WorkflowSpec(name="default").active_script() == s


def test_save_sets_notify_webhook(tmp_path) -> None:
    cfg = _project(tmp_path)
    wf = {"w": {"high": 0.8, "low": 0.5, "notify": "webhook"}}
    bad = save_workflows(cfg, workflows=wf, notify_webhook="ftp://x")
    assert not bad["ok"]
    assert save_workflows(cfg, workflows=wf, notify_webhook="https://example.com/h")["ok"]
    back = load_config(cfg.config_path)
    assert back.notify_webhook == "https://example.com/h"
    assert back.workflows["w"]["notify"] == "webhook"
    # blank keeps the stored URL
    assert save_workflows(back, workflows=wf)["ok"]
    assert load_config(cfg.config_path).notify_webhook == "https://example.com/h"


# --- review fixes: per-block loops, notify block, scope, assignments ----------


def _improve_script(**blk):
    return [{"type": "improve", **blk}]


class _Attempts(dict):
    def __missing__(self, key):
        return 1


def test_improve_block_max_loops_overrides_workflow(tmp_path, monkeypatch) -> None:
    cfg = _project(tmp_path)
    monkeypatch.setattr(wr, "_improve_attempts", lambda history, locale: _Attempts())
    # workflow default is 2 -> one prior attempt is allowed to continue
    _, res = _run(cfg, _improve_script(), dry_run=True)
    assert res.data["loops_exhausted"] == 0
    # block says 1 -> one prior attempt exhausts it
    _, res = _run(cfg, _improve_script(max_loops=1), dry_run=True)
    assert res.data["loops_exhausted"] == 3


def test_max_loops_validated_and_saved(tmp_path) -> None:
    cfg = _project(tmp_path)
    with pytest.raises(ValueError):
        normalize_script([{"type": "improve", "max_loops": 99}])
    with pytest.raises(ValueError):
        normalize_script([{"type": "improve", "max_loops": "x"}])
    with pytest.raises(ValueError):
        normalize_script([{"type": "stop", "max_loops": 1}])
    assert save_workflows(cfg, workflows={"w": {"script": _improve_script(max_loops=1)}})["ok"]
    back = load_config(cfg.config_path)
    assert back.workflows["w"]["script"][0]["max_loops"] == 1


def test_notify_block_posts_to_project_webhook(tmp_path, monkeypatch) -> None:
    cfg = _project(tmp_path)
    assert save_workflows(
        cfg, workflows={"w": {"script": [{"type": "notify"}]}},
        notify_webhook="https://example.com/h",
    )["ok"]
    sent = []
    monkeypatch.setattr(
        "llm_localizator.ops.notify.notify_webhook_async",
        lambda url, payload, **_kw: sent.append((url, payload)),
    )
    cfg = load_config(cfg.config_path)
    req = WorkflowRequest(name="w", route_only=True, locales=["pl"], namespace="app")
    assert op_workflow_run(cfg, req).ok
    assert sent and sent[0][0] == "https://example.com/h"
    assert sent[0][1]["event"] == "workflow.notify"
    sent.clear()
    dry = WorkflowRequest(name="w", route_only=True, locales=["pl"], namespace="app", dry_run=True)
    assert op_workflow_run(cfg, dry).ok
    assert not sent


def _two_locale_project(tmp_path):
    cfg = _project(tmp_path)
    text = cfg.config_path.read_text(encoding="utf-8")
    cfg.config_path.write_text(
        text.replace('targets = ["pl"]', 'targets = ["pl", "ar"]'), encoding="utf-8")
    return load_config(cfg.config_path)


def test_assignments_scope_default_overlap(tmp_path) -> None:
    from llm_localizator.ops.workflow import workflow_assignments, workflow_for_locale

    cfg = _two_locale_project(tmp_path)
    plain = {"high": 0.8, "low": 0.5}
    assert save_workflows(cfg, workflows={"default": plain})["ok"]
    cfg = load_config(cfg.config_path)
    a = workflow_assignments(cfg)
    assert a["byLocale"] == {"pl": "default", "ar": "default"}
    assert not a["overlaps"] and not a["uncovered"]

    assert save_workflows(cfg, workflows={
        "default": plain, "arabic": {**plain, "locales": ["ar"]},
    })["ok"]
    cfg = load_config(cfg.config_path)
    assert workflow_for_locale(cfg, "ar") == "arabic"
    assert workflow_for_locale(cfg, "pl") == "default"

    assert save_workflows(cfg, workflows={
        "b": {**plain, "locales": ["ar", "pl"]}, "a": {**plain, "locales": ["ar"]},
    })["ok"]
    cfg = load_config(cfg.config_path)
    a = workflow_assignments(cfg)
    assert a["byLocale"]["ar"] == "a"  # first alphabetically
    assert a["overlaps"] == {"ar": ["a", "b"]}

    assert save_workflows(cfg, workflows={"x": {**plain, "locales": ["pl"]}})["ok"]
    a = workflow_assignments(load_config(cfg.config_path))
    assert a["uncovered"] == ["ar"]


def test_scoped_workflow_never_touches_other_locale(tmp_path) -> None:
    cfg = _two_locale_project(tmp_path)
    assert save_workflows(cfg, workflows={"w": {
        "script": [{"type": "review_ticket"}], "locales": ["ar"],
    }})["ok"]
    cfg = load_config(cfg.config_path)
    req = WorkflowRequest(name="w", route_only=True, namespace="app")
    res = op_workflow_run(cfg, req)
    lines = res.data["run"]["lines"]
    assert lines and all(x.startswith("ar/") for x in lines)  # pl is out of scope


def test_add_workflow_merges_and_filters(tmp_path) -> None:
    from llm_localizator.web.workflow_config import add_workflow

    cfg = _project(tmp_path)  # has [workflows.default]
    row = {"script": [{"type": "verify"}], "locales": ["pl", "de"]}
    res = add_workflow(cfg, name="extra", row=row)
    assert res["ok"] and res["droppedLocales"] == ["de"]
    back = load_config(cfg.config_path)
    assert set(back.workflows) == {"default", "extra"}
    assert back.workflows["extra"]["locales"] == ["pl"]
    refuse = add_workflow(back, name="extra", row=row)
    assert not refuse["ok"] and "already exists" in refuse["error"]
    assert add_workflow(back, name="extra", row=row, overwrite=True)["ok"]
    assert not add_workflow(back, name="bad", row={"script": [{"type": "nope"}]})["ok"]


def test_workflow_js_contracts() -> None:
    from pathlib import Path

    static = Path(__file__).resolve().parent.parent / "llm_localizator" / "web" / "static"
    js = (static / "workflow.js").read_text(encoding="utf-8")
    assert '"project-select"' in js and 'addEventListener("change"' in js
    assert "/api/workflow/copy" in js
    en = json.loads((static.parent / "locales" / "en.json").read_text(encoding="utf-8"))
    import re

    used = set(re.findall(r'\bt\(\s*"(wf_[a-z0-9_]+)"', js))
    missing = sorted(k for k in used if not k.endswith("_") and k not in en)
    assert not missing, missing


def test_run_id_rejects_trailing_newline_and_cancel_does_not_block(tmp_path) -> None:
    import threading
    from types import SimpleNamespace

    cfg = SimpleNamespace(state_root=lambda: tmp_path)

    from llm_localizator.ops import workflow_run as wr

    assert wr.RUN_ID.fullmatch("wf_abcdef") and not wr.RUN_ID.fullmatch("wf_abcdef\n")
    assert wr.load_run(None, "wf_abcdef\n") is None

    # A run that is busy in another thread must not block cancel for others.
    lock = wr._run_lock("wf_busy123")
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with lock:
            held.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    try:
        assert wr.cancel_run(cfg, "wf_busy123") is None  # unknown record, but returned
        assert wr._cancel_flag("wf_busy123").is_set()
    finally:
        release.set()
        t.join()
        wr._release_run("wf_busy123", "canceled")


def test_every_preset_is_valid_and_listed() -> None:
    from llm_localizator.core.workflow_rules import PRESETS, presets

    rows = presets()
    assert [r["id"] for r in rows] == list(PRESETS)
    assert "tm_llm_validate" in PRESETS
    for row in rows:
        assert normalize_script(row["script"]) == row["script"]


def test_validate_block_passes_keys_through(tmp_path) -> None:
    cfg = _project(tmp_path)
    script = [{"type": "validate"}, {**_cond(0.8), "then": [{"type": "verify"}], "else": []}]
    cfg, res = _run(cfg, script)
    assert res.ok
    assert res.data["validated"] == 3
    assert res.data["verified"] == 1


def test_prune_keeps_active_runs(tmp_path) -> None:
    """Terminal prune must never delete waiting/running records (T0.1)."""
    cfg = _project(tmp_path)
    runs = wr._runs_dir(cfg)
    runs.mkdir(parents=True, exist_ok=True)
    waiting_id = "wf_20261123T120000_aabbcc"
    for i in range(wr.KEEP_RUNS + 5):
        rid = f"wf_20261123T{i:06d}_term{i:02d}"
        (runs / f"{rid}.json").write_text(json.dumps({
            "id": rid, "status": "done", "frontier": [], "stats": {}, "counts": {},
        }), encoding="utf-8")
    (runs / f"{waiting_id}.json").write_text(json.dumps({
        "id": waiting_id, "status": "waiting",
        "frontier": [{"pos": [0], "keys": [], "wait": {"tasks": ["t1"], "kind": "rescore", "at": "x"}}],
        "stats": {}, "counts": {},
    }), encoding="utf-8")
    wr._prune_old_runs(cfg)
    assert (runs / f"{waiting_id}.json").is_file()
    terminal = [p for p in runs.glob("wf_*.json") if p.stem != waiting_id]
    assert len(terminal) <= wr.KEEP_RUNS


def test_resume_stalled_running(tmp_path, monkeypatch) -> None:
    """A kill mid-advance leaves status=running; resume must continue (T0.2)."""
    cfg = _project(tmp_path)
    monkeypatch.setattr(wr, "tq_available", lambda: False)
    assert save_workflows(cfg, workflows={"w": {"script": [
        {"type": "flag"}, {"type": "review_ticket"},
    ]}})["ok"]
    cfg = load_config(cfg.config_path)
    from llm_localizator.ops.workflow import get_workflow
    spec = get_workflow(cfg, "w")
    rid = "wf_20261123T130000_stall1"
    # Mid-run checkpoint: first terminal block still pending on the frontier.
    wr._save_run(cfg, {
        "id": rid,
        "workflow": "w",
        "status": "running",
        "dryRun": False,
        "useQueue": False,
        "scope": {"locales": ["pl"], "namespace": "app", "namespaces": None},
        "frontier": [{"pos": [0], "keys": None, "wait": None}],
        "counts": {},
        "stats": {},
        "lines": [],
        "message": "",
        "started": "2026-11-23T13:00:00Z",
        "finished": None,
    })
    res = wr.resume_run(cfg, spec, rid)
    assert res is not None and res.ok
    assert wr.load_run(cfg, rid)["status"] == "done"
    assert len(ReviewQueue(cfg.review_root()).list_tickets("pl")) == 3
