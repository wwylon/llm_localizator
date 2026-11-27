"""Operations layer tests."""

from __future__ import annotations

from llm_localizator.cli.main import build_parser
from llm_localizator.ops import build_commands_manifest, dispatch_op
from llm_localizator.ops.types import ValidateRequest
from llm_localizator.ops.validate import op_validate

from tests.pipeline.test_translate import setup_project
from tests.conftest import write_json


def test_commands_manifest_includes_validate(project_root, make_config) -> None:
    manifest = build_commands_manifest(build_parser())
    assert "validate" in manifest["commands"]
    names = {f["name"] for f in manifest["commands"]["validate"]["fields"]}
    assert "semantic" in names or "check_expansion" in names


def test_op_validate_hermetic(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    result = op_validate(cfg, ValidateRequest())
    assert result.command == "validate"
    assert result.exit_code in (0, 1, 2)


def test_dispatch_validate(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    out = dispatch_op(cfg, "validate", {"semantic": True}, actor_role="Admin")
    assert out["command"] == "validate"
    assert "summary" in out


def test_dispatch_status(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    out = dispatch_op(cfg, "status", {}, actor_role="Admin")
    assert out["command"] == "status"
    assert "locales" in out["data"]


def test_dispatch_migrate_state(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    out = dispatch_op(cfg, "migrate-state", {"dry_run": True}, actor_role="Admin")
    assert out["command"] == "migrate-state"
    assert out["ok"] is True


def test_dispatch_scan_requires_adapter(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root)
    out = dispatch_op(cfg, "scan", {}, actor_role="Admin")
    assert out["command"] == "scan"
    assert out["ok"] is False


def test_dispatch_review_dry_run_loops_locales(project_root, make_config) -> None:
    """op_review must call run_review(locale=...) per locale, not locales=."""
    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    out = dispatch_op(cfg, "review", {"dry_run": True, "locales": ["pl"]}, actor_role="Admin")
    assert out["command"] == "review"
    assert out.get("ok") is True
    assert "checked" in out.get("data", {})


def test_op_translate_prefers_queue_when_tq_available(project_root, make_config, monkeypatch) -> None:
    """Non-dry-run translate must submit, never run_translation, when tq is up."""
    from llm_localizator.ops.translate import op_translate
    from llm_localizator.ops.types import TranslateRequest
    from llm_localizator.projects.taskqueue import SubmitOutcome

    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    called: list[tuple] = []

    def fake_submit_locales(c, locales, job="translate", overrides=None, **_kw):
        called.append((locales, overrides))
        return SubmitOutcome(0, "queued demo/localize_ui_messages__pl", ("demo/localize_ui_messages__pl",))

    monkeypatch.setattr("llm_localizator.ops.translate.tq_available", lambda: True)
    monkeypatch.setattr("llm_localizator.ops.enqueue.submit_locales", fake_submit_locales)

    def boom(*_a, **_k):
        raise AssertionError("run_translation must not run when tq is available")

    monkeypatch.setattr("llm_localizator.ops.translate.run_translation", boom)

    out = op_translate(cfg, TranslateRequest(locales=["pl"], submit=False))
    assert out.ok
    assert out.data.get("submitted") is True
    assert called and called[0][0] == ["pl"]
    # Plain operator runs retry the per-locale tasks (which bake --ignore-min-keys);
    # per-run options would turn the request into a one-off run.
    assert not called[0][1]


def test_op_translate_runs_locally_without_tq(project_root, make_config, monkeypatch) -> None:
    """CLI-style submit=True must still translate in-process when tq is absent."""
    from llm_localizator.ops.translate import op_translate
    from llm_localizator.ops.types import TranslateRequest
    from llm_localizator.pipeline.translate import TranslationResult

    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    monkeypatch.setattr("llm_localizator.ops.translate.tq_available", lambda: False)

    def fake_run(*_a, **_k):
        return TranslationResult(total=1, written=1, rejected=[], skipped=[], dry_run=False)

    monkeypatch.setattr("llm_localizator.ops.translate.run_translation", fake_run)

    def boom_submit(*_a, **_k):
        raise AssertionError("must not call tq when it is not on PATH")

    monkeypatch.setattr("llm_localizator.ops.translate._submit", boom_submit)
    out = op_translate(cfg, TranslateRequest(locales=["pl"], submit=True))
    assert out.ok
    assert out.data.get("submitted") is not True



def test_op_translate_submits_below_min_keys(project_root, make_config, monkeypatch) -> None:
    """Operator translate must enqueue even when backlog is under min_keys."""
    from llm_localizator.ops.translate import op_translate
    from llm_localizator.ops.types import TranslateRequest
    from llm_localizator.projects.taskqueue import SubmitOutcome

    setup_project(project_root, {"a": "A", "b": "B"})
    cfg = make_config(project_root, translate_min_keys=50)
    called: list[tuple] = []

    def fake_submit_locales(c, locales, job="translate", overrides=None, **_kw):
        called.append((locales, overrides))
        return SubmitOutcome(0, "queued demo/localize_ui_messages__pl", ("demo/localize_ui_messages__pl",))

    monkeypatch.setattr("llm_localizator.ops.translate.tq_available", lambda: True)
    monkeypatch.setattr("llm_localizator.ops.enqueue.submit_locales", fake_submit_locales)

    out = op_translate(cfg, TranslateRequest(locales=["pl"]))
    assert out.ok
    assert out.data.get("submitted") is True
    assert called and called[0][0] == ["pl"]
    # Plain operator runs retry the per-locale tasks (which bake --ignore-min-keys);
    # per-run options would turn the request into a one-off run.
    assert not called[0][1]


def test_op_translate_dry_run_stays_local(project_root, make_config, monkeypatch) -> None:
    from llm_localizator.ops.translate import op_translate
    from llm_localizator.ops.types import TranslateRequest
    from llm_localizator.pipeline.translate import TranslationResult

    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    monkeypatch.setattr("llm_localizator.ops.translate.tq_available", lambda: True)

    def fake_run(*_a, **_k):
        return TranslationResult(total=0, written=0, rejected=[], skipped=[], dry_run=True)

    monkeypatch.setattr("llm_localizator.ops.translate.run_translation", fake_run)
    out = op_translate(cfg, TranslateRequest(locales=["pl"], dry_run=True))
    assert out.ok
    assert out.data.get("dryRun") is True
    assert "submitted" not in (out.data or {})


def test_op_rescore_prefers_queue_when_tq_available(project_root, make_config, monkeypatch) -> None:
    """Non-dry-run rescore must submit, never project_provider, when tq is up."""
    from llm_localizator.ops.rescore import op_rescore
    from llm_localizator.ops.types import RescoreRequest
    from llm_localizator.projects.taskqueue import SubmitOutcome

    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    called: list[dict] = []

    def fake_submit(c, job="rescore", overrides=None, **_kw):
        called.append({"job": job, "overrides": overrides or {}})
        return SubmitOutcome(0, "queued demo/localize_rescore", ("demo/localize_rescore",))

    monkeypatch.setattr("llm_localizator.ops.rescore.tq_available", lambda: True)
    monkeypatch.setattr("llm_localizator.ops.enqueue.submit", fake_submit)

    def boom(*_a, **_k):
        raise AssertionError("project_provider must not run when tq is available")

    monkeypatch.setattr("llm_localizator.ops.rescore.project_provider", boom)

    out = op_rescore(cfg, RescoreRequest(locales=["pl"], submit=False))
    assert out.ok
    assert out.data.get("submitted") is True
    assert called and called[0]["job"] == "rescore"
    assert called[0]["overrides"].get("--locales") == "pl"


def test_op_rescore_dry_run_stays_local(project_root, make_config, monkeypatch) -> None:
    from llm_localizator.ops.rescore import op_rescore
    from llm_localizator.ops.types import RescoreRequest

    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    monkeypatch.setattr("llm_localizator.ops.rescore.tq_available", lambda: True)

    def boom(*_a, **_k):
        raise AssertionError("submit must not run on dry-run")

    monkeypatch.setattr("llm_localizator.ops.enqueue.submit", boom)

    out = op_rescore(cfg, RescoreRequest(locales=["pl"], dry_run=True))
    assert out.ok
    assert out.data.get("dryRun") is True
    assert "submitted" not in (out.data or {})


def test_op_init_detects_layout(tmp_path) -> None:
    from llm_localizator.ops.init import op_init
    from llm_localizator.ops.types import InitRequest

    (tmp_path / "messages" / "en").mkdir(parents=True)
    write_json(tmp_path / "messages" / "en" / "app.json", {"hi": "Hi"})
    result = op_init(InitRequest(directory=str(tmp_path), no_register=True))
    assert result.ok
    assert (tmp_path / ".llm-localize.toml").is_file()
