"""--keys on review and rescore: filtering, unknown-key reporting, parity."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.cli.main import build_parser
from llm_localizator.ops import rescore as rescore_mod
from llm_localizator.ops import review as review_mod
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.rescore import op_rescore
from llm_localizator.ops.review import op_review
from llm_localizator.ops.types import RescoreRequest, ReviewRequest
from llm_localizator.pipeline.review import run_review
from llm_localizator.providers import NullProvider

from tests.conftest import setup_project


@pytest.fixture
def seeded(project_root, make_config, make_catalog):
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"},
                  existing={"greet": "Witaj", "bye": "Zegnaj"})
    cfg = make_config(project_root)
    state = StateStore(cfg.state_dir)
    for key, src in (("greet", "Hello"), ("bye", "Goodbye")):
        state.record("pl", "app", key, make_entry(src, "testmodel"))
    state.save("pl")
    return cfg, make_catalog(cfg)


def test_run_review_only_sends_named_keys(seeded, silent) -> None:
    cfg, catalog = seeded
    prompts: list[str] = []

    def handler(req):
        prompts.append(req.prompt)
        return json.dumps([{"index": 0, "verdict": "ok"}])

    result = run_review(
        cfg, catalog, NullProvider(handler=handler), locale="pl",
        keys=["app.greet", "app.nope"], report=silent,
    )
    assert result.checked == 1
    assert "Witaj" in prompts[0] and "Zegnaj" not in prompts[0]
    assert result.unknown_keys == ["app.nope"]


def test_op_review_reports_unknown_keys(seeded, monkeypatch) -> None:
    cfg, _ = seeded
    monkeypatch.setattr(review_mod, "tq_available", lambda: False)
    monkeypatch.setattr(review_mod, "project_provider",
                        lambda c: NullProvider(handler=lambda r: json.dumps([{"index": 0, "verdict": "ok"}])))
    res = op_review(cfg, ReviewRequest(locales=["pl"], keys=["app.greet", "app.nope"]))
    assert res.data["unknownKeys"] == ["app.nope"]
    assert any("app.nope" in ln for ln in res.lines)


def test_op_rescore_reports_unknown_keys_dry_run(seeded) -> None:
    cfg, _ = seeded
    res = op_rescore(cfg, RescoreRequest(locales=["pl"], keys=["app.greet", "app.nope"], dry_run=True))
    assert res.data["total"] == 1
    assert res.data["unknownKeys"] == ["app.nope"]
    assert any("app.nope" in ln for ln in res.lines)


def test_rescore_submit_override_keys(seeded, monkeypatch) -> None:
    cfg, _ = seeded
    seen: dict = {}

    def fake_enqueue(c, job, overrides, namespaces):
        seen.update(overrides)
        return True, ["queued"], []

    monkeypatch.setattr(rescore_mod, "enqueue_namespace_jobs", fake_enqueue)
    monkeypatch.setattr(rescore_mod, "tq_available", lambda: True)
    op_rescore(cfg, RescoreRequest(locales=["pl"], keys=["app.a", "app.b"], submit=True))
    assert seen["--keys"] == "app.a,app.b"


def test_dispatch_review_and_rescore_keys(seeded, monkeypatch) -> None:
    cfg, _ = seeded
    got: dict = {}
    # No tq required: default operator path runs locally without confirm.
    monkeypatch.setattr("llm_localizator.projects.taskqueue.tq_available", lambda: False)
    monkeypatch.setattr("llm_localizator.ops.dispatch_cmds.op_review",
                        lambda c, req, report=None: got.update(review=req.keys) or review_mod.OpResult(
                            ok=True, exit_code=0, command="review", summary=""))
    monkeypatch.setattr("llm_localizator.ops.dispatch_cmds.op_rescore",
                        lambda c, req, report=None: got.update(rescore=req.keys) or review_mod.OpResult(
                            ok=True, exit_code=0, command="rescore", summary=""))
    dispatch_op(cfg, "review", {"keys": "app.a, app.b"}, actor_role="Admin")
    dispatch_op(cfg, "rescore", {"keys": ["app.c"]}, actor_role="Admin")
    assert got == {"review": ["app.a", "app.b"], "rescore": ["app.c"]}


@pytest.mark.parametrize("cmd", ["review", "run-review", "rescore", "run-rescore"])
def test_cli_parses_keys(cmd) -> None:
    args = build_parser().parse_args([cmd, "--keys", "app.a,app.b", "--keys", "app.c"])
    assert args.keys == ["app.a,app.b", "app.c"]
