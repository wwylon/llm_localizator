"""W-10 — workflow routing, branches, merge conflicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.catalog.history import HistoryStore, make_history_event
from llm_localizator.catalog.review_queue import ReviewQueue
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.state import StateStore, make_entry
from llm_localizator.core.hash import src_hash
from llm_localizator.ops.verify import verify_translation
from llm_localizator.ops.workflow import (
    WorkflowRequest,
    get_workflow,
    op_workflow_run,
    route_action,
)
from llm_localizator.projects.branches import (
    branch_config,
    merge_preview,
    merge_resolve,
    sync_from_git,
    track_branch,
)
from llm_localizator.projects.config import load_config
from llm_localizator.web.shell import render_shell
from llm_localizator.web.workflow_config import get_named_workflow, save_workflows, workflow_view

from .conftest import setup_project


@pytest.fixture(autouse=True)
def _no_taskqueue(monkeypatch):
    """Hermetic: LLM blocks run in-process (a real ``tq`` may be on PATH)."""
    monkeypatch.setattr("llm_localizator.ops.workflow_run.tq_available", lambda: False)


def _toml(root: Path) -> Path:
    path = root / ".llm-localize.toml"
    path.write_text(
        "[project]\n"
        "name = \"demo\"\n"
        "source_locale = \"en\"\n"
        "\n"
        "[catalog]\n"
        "format = \"json-nested\"\n"
        "path = \"messages/{locale}/{namespace}.json\"\n"
        "\n"
        "[locales]\n"
        "targets = [\"pl\"]\n"
        "\n"
        "[provider]\n"
        "kind = \"null\"\n"
        "\n"
        "[state]\n"
        "dir = \"messages/.state\"\n"
        "\n"
        "[workflows.default]\n"
        "high = 0.80\n"
        "low = 0.55\n",
        encoding="utf-8",
    )
    return path


def test_route_action_three_bands() -> None:
    assert route_action(0.90, high=0.80, low=0.55) == "verify"
    assert route_action(0.40, high=0.80, low=0.55) == "improve"
    assert route_action(0.70, high=0.80, low=0.55) == "review"


def test_three_scores_take_three_branches(tmp_path, make_config) -> None:
    setup_project(tmp_path, {
        "hi": "High",
        "lo": "Low",
        "mid": "Mid",
    }, existing={"hi": "H", "lo": "L", "mid": "M"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    store = StateStore(cfg.state_root())
    for key, src in (("hi", "High"), ("lo", "Low"), ("mid", "Mid")):
        store.record("pl", "app", key, make_entry(src, "testmodel", provider="ollama"))
    store.save("pl")
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "hi", score=0.90, signals=[], text="H")
    scores.record("pl", "app", "lo", score=0.40, signals=[], text="L")
    scores.record("pl", "app", "mid", score=0.70, signals=[], text="M")
    scores.save("pl")

    result = op_workflow_run(cfg, WorkflowRequest(
        name="default", route_only=True, locales=["pl"], namespace="app",
    ))
    assert result.ok
    assert result.data["verified"] == 1
    assert result.data["tickets"] == 1
    # improve may keep or change with null provider; it was attempted
    assert "improve" in " ".join(result.lines)

    entry = StateStore(cfg.state_root()).entry("pl", "app", "hi")
    assert entry is not None
    assert entry.get("verified_by") == "workflow"
    assert entry.get("provider") == "ollama"
    assert entry.get("provider") != "human"

    tickets = ReviewQueue(cfg.review_root()).list_tickets("pl")
    assert any(t.key == "mid" and t.reason == "low_score" for t in tickets)


def test_cooldown_blocks_repeat_improve(tmp_path) -> None:
    setup_project(tmp_path, {"lo": "Low"}, existing={"lo": "L"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    # Force long cooldown already satisfied by a fresh improve-reject event.
    store = StateStore(cfg.state_root())
    store.record("pl", "app", "lo", make_entry("Low", "testmodel", provider="ollama"))
    store.save("pl")
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "lo", score=0.20, signals=[], text="L")
    scores.save("pl")
    HistoryStore(cfg.history_root()).append(
        "pl",
        make_history_event(
            namespace="app", key="lo", prev="L", next_text="L",
            model="testmodel", status="machine",
            src_sha=src_hash("Low"), trigger="improve-reject",
            provider="ollama",
        ),
    )

    calls = {"n": 0}
    from llm_localizator.ops import workflow as wf_mod
    real_improve = wf_mod.op_improve

    def counting_improve(cfg, req, **kwargs):
        calls["n"] += 1
        return real_improve(cfg, req, **kwargs)

    wf_mod.op_improve = counting_improve  # type: ignore[assignment]
    try:
        result = op_workflow_run(cfg, WorkflowRequest(
            name="default", route_only=True, locales=["pl"], namespace="app",
        ))
    finally:
        wf_mod.op_improve = real_improve  # type: ignore[assignment]
    assert result.ok
    assert result.data["skipped_cooldown"] >= 1
    assert calls["n"] == 0


def test_verify_does_not_rewrite_provider(tmp_path) -> None:
    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    store = StateStore(cfg.state_root())
    store.record("pl", "app", "greet", make_entry("Hello", "m", provider="ollama"))
    store.save("pl")
    result = verify_translation(
        cfg, locale="pl", namespace="app", key="greet", verified_by="workflow",
    )
    assert result["ok"] is True
    assert result["provider"] == "ollama"
    entry = StateStore(cfg.state_root()).entry("pl", "app", "greet")
    assert entry["verified_by"] == "workflow"
    assert entry["provider"] == "ollama"
    assert entry["provider"] != "human"


def test_workflow_save_reloads(tmp_path) -> None:
    _toml(tmp_path)
    (tmp_path / "messages" / "en").mkdir(parents=True)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    result = save_workflows(cfg, workflows={
        "default": {"high": 0.85, "low": 0.50},
        "strict": {"high": 0.95, "low": 0.40},
    })
    assert result["ok"] is True
    reloaded = load_config(tmp_path / ".llm-localize.toml")
    assert reloaded.workflows["default"]["high"] == 0.85
    assert get_workflow(reloaded, "strict").low == 0.40
    view = workflow_view(reloaded)
    assert {w["name"] for w in view["workflows"]} == {"default", "strict"}


def test_unknown_workflow_fails_load(tmp_path) -> None:
    _toml(tmp_path)
    (tmp_path / "messages" / "en").mkdir(parents=True)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    bad = get_named_workflow(cfg, "nope")
    assert bad["ok"] is False
    result = op_workflow_run(cfg, WorkflowRequest(name="nope", route_only=True))
    assert result.ok is False
    assert "unknown workflow" in result.summary


def test_track_branch_no_catalogue_copy(tmp_path) -> None:
    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    en = tmp_path / "messages" / "en" / "app.json"
    pl = tmp_path / "messages" / "pl" / "app.json"
    before_en = en.read_bytes()
    before_pl = pl.read_bytes()
    result = track_branch(cfg, "feat-x")
    assert result["ok"] is True
    branch_dir = cfg.state_root() / "branches" / "feat-x"
    assert branch_dir.is_dir()
    assert (branch_dir / "scores").is_dir()
    assert en.read_bytes() == before_en
    assert pl.read_bytes() == before_pl
    assert not (branch_dir / "app.json").exists()
    overlay = branch_config(cfg, "feat-x")
    assert overlay is not None
    assert overlay.state_root() == branch_dir
    assert overlay.catalog_path == cfg.catalog_path


def test_sync_does_not_commit(tmp_path) -> None:
    setup_project(tmp_path, {"greet": "Hello"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    # Not necessarily a git repo — sync should still report committed=False.
    result = sync_from_git(cfg)
    assert result.get("committed") is False


def test_merge_conflict_untouched_until_chosen(tmp_path) -> None:
    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Main"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    track_branch(cfg, "feat")
    main = StateStore(cfg.state_root())
    main.record("pl", "app", "greet", make_entry("Hello", "main-model", provider="ollama"))
    main.save("pl")
    bcfg = branch_config(cfg, "feat")
    assert bcfg is not None
    branch = StateStore(bcfg.state_root())
    branch.record("pl", "app", "greet", make_entry("Hello", "branch-model", provider="ollama"))
    branch.save("pl")

    preview = merge_preview(cfg, "feat")
    assert preview["ok"] is True
    assert preview["conflicts"] >= 1
    before = main.entry("pl", "app", "greet")["model"]

    # Keep main — unchanged.
    merge_resolve(cfg, "feat", choices=[{
        "locale": "pl", "namespace": "app", "key": "greet", "side": "main",
    }])
    assert StateStore(cfg.state_root()).entry("pl", "app", "greet")["model"] == before

    # Take branch.
    merge_resolve(cfg, "feat", choices=[{
        "locale": "pl", "namespace": "app", "key": "greet", "side": "branch",
    }])
    assert StateStore(cfg.state_root()).entry("pl", "app", "greet")["model"] == "branch-model"


def test_rules_first_match_and_else() -> None:
    from llm_localizator.core.workflow_rules import evaluate_rules, normalize_workflow

    wf = normalize_workflow({"rules": [
        {"field": "locale", "op": "is", "value": "de", "action": "flag"},
        {"field": "score", "op": "ge", "value": 0.9, "action": "verify"},
        {"field": "status", "op": "is_not", "value": "human", "action": "llm_review"},
        {"field": "namespace", "op": "is", "value": "app", "action": "improve"},
    ]})
    rules = wf["rules"]
    base = {"score": 0.95, "status": "human", "locale": "pl", "namespace": "x"}
    assert evaluate_rules(rules, base) == "verify"
    assert evaluate_rules(rules, {**base, "locale": "de"}) == "flag"  # first match wins
    assert evaluate_rules(rules, {**base, "score": 0.5}) == "review"  # ELSE
    assert evaluate_rules(rules, {**base, "score": 0.5, "status": "machine"}) == "llm_review"
    assert evaluate_rules(rules, {**base, "score": 0.5, "namespace": "app"}) == "improve"
    assert wf["high"] == 0.9 and wf["low"] == 0.55


def test_normalize_rejects_bad_workflows() -> None:
    import pytest

    from llm_localizator.core.workflow_rules import normalize_workflow

    bad = [
        {"rules": [{"field": "nope", "op": "is", "value": "x", "action": "flag"}]},
        {"rules": [{"field": "score", "op": "is", "value": 0.5, "action": "flag"}]},
        {"rules": [{"field": "score", "op": "ge", "value": 1.5, "action": "flag"}]},
        {"rules": [{"field": "locale", "op": "is", "value": "", "action": "flag"}]},
        {"rules": [{"field": "locale", "op": "is", "value": "de", "action": "boom"}]},
        {"max_improve_loops": 9},
        {"notify": "email"},
        {"high": 0.3, "low": 0.6},
        {"surprise": 1},
    ]
    for table in bad:
        with pytest.raises(ValueError):
            normalize_workflow(table)


def test_save_rules_roundtrip_and_canonical_compaction(tmp_path) -> None:
    _toml(tmp_path)
    (tmp_path / "messages" / "en").mkdir(parents=True)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    rules = [
        {"field": "score", "op": "ge", "value": 0.9, "action": "verify"},
        {"field": "locale", "op": "is", "value": "pl", "action": "flag"},
    ]
    result = save_workflows(cfg, workflows={
        "plain": {"high": 0.8, "low": 0.5, "maxImproveLoops": 2},
        "rich": {"rules": rules, "maxImproveLoops": 3, "notify": "webhook", "locales": ["pl"]},
    })
    assert result["ok"] is True
    text = (tmp_path / ".llm-localize.toml").read_text(encoding="utf-8")
    plain_block = text.split("[workflows.plain]")[1].split("[workflows.rich]")[0]
    assert "rules" not in plain_block
    reloaded = load_config(tmp_path / ".llm-localize.toml")
    rich = get_workflow(reloaded, "rich")
    assert list(rich.rules) == [
        {"field": "score", "op": "ge", "value": 0.9, "action": "verify"},
        {"field": "locale", "op": "is", "value": "pl", "action": "flag"},
    ]
    assert rich.max_improve_loops == 3 and rich.notify == "webhook"
    assert rich.locales == ("pl",)
    bad = save_workflows(cfg, workflows={"x": {"max_improve_loops": 99}})
    assert bad["ok"] is False


def _seed_scored(tmp_path, scores_by_key: dict[str, float]):
    texts = {k: k.title() for k in scores_by_key}
    setup_project(tmp_path, texts, existing={k: k.upper() for k in scores_by_key})
    cfg_path = _toml(tmp_path)
    return cfg_path, texts


def test_flag_and_review_actions_route(tmp_path) -> None:
    from llm_localizator.catalog.flags import FlagStore

    _seed_scored(tmp_path, {"a": 0.9, "b": 0.7})
    path = tmp_path / ".llm-localize.toml"
    path.write_text(
        path.read_text(encoding="utf-8").split("[workflows.default]")[0]
        + "[workflows.default]\nmax_improve_loops = 2\n"
        + "[[workflows.default.rules]]\nfield = \"score\"\nop = \"ge\"\nvalue = 0.8\naction = \"flag\"\n",
        encoding="utf-8",
    )
    text = path.read_text(encoding="utf-8")
    if "[state]" in text:
        text = text.replace("[state]", '[state]\nflags = ".flags.jsonl"', 1)
    else:
        text = '[state]\nflags = ".flags.jsonl"\n' + text
    path.write_text(text, encoding="utf-8")
    cfg = load_config(path)
    store = StateStore(cfg.state_root())
    scores = ScoreStore(cfg.scores_root())
    for key, score in (("a", 0.9), ("b", 0.7)):
        store.record("pl", "app", key, make_entry(key.title(), "m", provider="ollama"))
        scores.record("pl", "app", key, score=score, signals=[], text=key.upper())
    store.save("pl")
    scores.save("pl")

    result = op_workflow_run(cfg, WorkflowRequest(
        name="default", route_only=True, locales=["pl"], namespace="app",
    ))
    assert result.ok
    assert result.data["flagged"] == 1 and result.data["tickets"] == 1
    assert result.data["routed"] == 2
    assert any(r.get("key") == "a" for r in FlagStore(cfg.flags_path).rows())
    from llm_localizator.ops.workflow import load_last_runs

    assert load_last_runs(cfg)["default"]["flagged"] == 1


def test_dry_run_does_not_persist_last_run(tmp_path) -> None:
    from llm_localizator.ops.workflow import load_last_runs

    _seed_scored(tmp_path, {"a": 0.9})
    cfg = load_config(tmp_path / ".llm-localize.toml")
    result = op_workflow_run(cfg, WorkflowRequest(
        name="default", route_only=True, dry_run=True, locales=["pl"], namespace="app",
    ))
    assert result.ok
    assert load_last_runs(cfg) == {}


def test_improve_loops_exhausted_becomes_ticket(tmp_path) -> None:
    setup_project(tmp_path, {"lo": "Low"}, existing={"lo": "L"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    store = StateStore(cfg.state_root())
    store.record("pl", "app", "lo", make_entry("Low", "m", provider="ollama"))
    store.save("pl")
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "lo", score=0.2, signals=[], text="L")
    scores.save("pl")
    hist = HistoryStore(cfg.history_root())
    for _ in range(2):
        hist.append("pl", make_history_event(
            namespace="app", key="lo", prev="L", next_text="L", model="m",
            status="machine", src_sha=src_hash("Low"), trigger="improve-reject",
            provider="ollama",
        ))
    result = op_workflow_run(cfg, WorkflowRequest(
        name="default", route_only=True, locales=["pl"], namespace="app",
    ))
    assert result.data["loops_exhausted"] == 1
    assert result.data["tickets"] == 1
    assert result.data["skipped_cooldown"] == 0


def test_locale_scope_limits_run(tmp_path) -> None:
    _seed_scored(tmp_path, {"a": 0.9})
    path = tmp_path / ".llm-localize.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("low = 0.55\n", "low = 0.55\nlocales = [\"de\"]\n"),
        encoding="utf-8",
    )
    cfg = load_config(path)
    result = op_workflow_run(cfg, WorkflowRequest(
        name="default", route_only=True, locales=["pl"], namespace="app",
    ))
    assert result.data["routed"] == 0


def test_workflow_help_registered() -> None:
    from llm_localizator.web.shell import _PAGE_SCRIPTS

    static = Path(__file__).resolve().parent.parent / "llm_localizator" / "web" / "static"
    assert "/static/help.js" not in _PAGE_SCRIPTS["workflow"]
    import json

    help_keys = json.loads((static.parent / "locales" / "help" / "en.json").read_text(encoding="utf-8"))
    for key in ("workflow:general", "workflow:blocks", "workflow:run", "workflow:config", "workflow:history"):
        assert key in help_keys
    wf_js = (static / "workflow.js").read_text(encoding="utf-8")
    assert 'help("workflow:general")' in wf_js
    import re

    for used in set(re.findall(r'help\("(workflow:[a-z]+)"\)', wf_js)):
        assert used in help_keys, used
    html = render_shell("workflow")
    assert "__LLM_ENSURE_HELP" in html or "requestIdleCallback" in html


def test_pages_render() -> None:
    for route in ("workflow", "branches"):
        html = render_shell(route)
        assert f'data-page="{route}"' in html
        assert f"/static/{route}.js" in html


def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root, check=True, capture_output=True,
    )


def test_branch_source_diff_reads_git_without_checkout(tmp_path) -> None:
    import json

    from llm_localizator.projects.branches import branch_source_diff

    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "feat")
    en = tmp_path / "messages" / "en" / "app.json"
    en.write_text(json.dumps({"greet": "Hello!", "bye": "Bye"}), encoding="utf-8")
    _git(tmp_path, "commit", "-am", "feat")
    _git(tmp_path, "checkout", "main")
    before = en.read_bytes()

    diff = branch_source_diff(cfg, "feat", "main")
    assert diff["ok"] is True
    assert ("app", "bye") in [tuple(k) for k in diff["added"]]
    assert ("app", "greet") in [tuple(k) for k in diff["changed"]]
    assert en.read_bytes() == before


def test_merge_new_and_take_apply_and_mark_merged(tmp_path) -> None:
    setup_project(tmp_path, {"greet": "Hello"})
    _toml(tmp_path)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    track_branch(cfg, "feat")
    bcfg = branch_config(cfg, "feat")
    branch = StateStore(bcfg.state_root())
    branch.record("pl", "app", "greet", make_entry("Hello", "m", provider="ollama"))
    branch.save("pl")
    preview = merge_preview(cfg, "feat")
    assert preview["new"] == 1 and preview["conflicts"] == 0
    result = merge_resolve(cfg, "feat", choices=[])
    assert result["merged"] is True and result["applied"] == 1
    assert StateStore(cfg.state_root()).entry("pl", "app", "greet")["model"] == "m"
    from llm_localizator.projects.branches import list_branches

    rows = {b["name"]: b for b in list_branches(cfg)["branches"]}
    assert rows["feat"]["status"] == "merged"
