"""The guided-setup checklist: one state machine, driven from fixture projects."""

from __future__ import annotations

import json

import pytest

from llm_localizator.ops import guide as guide_mod
from llm_localizator.ops.guide import op_guide
from llm_localizator.ops.types import GuideRequest
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.projects.config import ProviderConfig
from llm_localizator.providers import NullProvider

from tests.conftest import setup_project, tagged, write_json


def _steps(result) -> dict[str, dict]:
    return {s["id"]: s for s in result.data["steps"]}


def _req(**kw) -> GuideRequest:
    return GuideRequest(skip_provider=True, **kw)


def test_empty_folder_lists_supported_layouts_and_next_is_project(tmp_path) -> None:
    result = op_guide(None, _req(directory=str(tmp_path)))
    steps = _steps(result)
    assert result.data["hasConfig"] is False
    assert result.data["next"] == "project"
    assert steps["project"]["status"] == "todo"
    assert "Supported layouts" in steps["project"]["detail"]
    assert "--format json-flat --path" in steps["project"]["detail"]
    assert steps["project"]["cli"] == "llm-localizator init"
    assert steps["languages"]["status"] == "todo"


def test_catalogue_without_config_is_detected(tmp_path) -> None:
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})
    steps = _steps(op_guide(None, _req(directory=str(tmp_path))))
    assert "Found a json-nested catalogue" in steps["project"]["detail"]
    assert steps["project"]["status"] == "todo"


def test_config_without_targets_asks_for_a_language(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root, targets=[], translate_approach="local")
    result = op_guide(cfg, _req())
    steps = _steps(result)
    assert steps["project"]["status"] == "done"
    assert steps["languages"]["status"] == "todo"
    assert steps["languages"]["cli"] == "llm-localizator add-locale --locale pl"
    assert result.data["next"] == "languages"


def test_empty_source_catalogue_is_reported(project_root, make_config) -> None:
    setup_project(project_root, {})
    steps = _steps(op_guide(make_config(project_root), _req()))
    assert steps["project"]["status"] == "todo"
    assert "no keys" in steps["project"]["detail"]


def test_untranslated_project_points_at_run_translate(
    project_root, make_config, monkeypatch,
) -> None:
    monkeypatch.setattr(
        "llm_localizator.projects.taskqueue.tq_available", lambda: False,
    )
    setup_project(project_root, {"a": "A", "b": "B"})
    result = op_guide(make_config(project_root, translate_approach="local"), _req())
    steps = _steps(result)
    assert steps["languages"]["status"] == "done"
    assert steps["translate"]["status"] == "todo"
    assert "2 string(s)" in steps["translate"]["detail"]
    assert steps["translate"]["cli"] == "llm-localizator run-translate"
    assert result.data["next"] == "translate"
    assert steps["review"]["status"] == "todo"


def test_untranslated_project_prefers_translate_when_tq_available(
    project_root, make_config, monkeypatch,
) -> None:
    monkeypatch.setattr(
        "llm_localizator.projects.taskqueue.tq_available", lambda: True,
    )
    setup_project(project_root, {"a": "A", "b": "B"})
    steps = _steps(op_guide(make_config(project_root), _req()))
    assert steps["translate"]["cli"] == "llm-localizator translate"
    assert "Taskqueue" in steps["translate"]["detail"]


def test_finished_project_completes_the_guide(
    project_root, make_config, make_catalog, silent,
) -> None:
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root)
    run_translation(cfg, make_catalog(cfg), NullProvider(handler=tagged), report=silent)
    result = op_guide(cfg, _req())
    steps = _steps(result)
    assert steps["translate"]["status"] == "done"
    assert steps["model"]["status"] == "done"
    assert steps["review"]["status"] in ("done", "todo")
    assert result.data["done"] >= 5


def test_ollama_down_names_the_fix(project_root, make_config, monkeypatch) -> None:
    monkeypatch.setattr(guide_mod, "ollama_state", lambda url: (False, []))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root, provider=ProviderConfig(kind="ollama"))
    result = op_guide(cfg, GuideRequest())
    env = _steps(result)["environment"]
    assert env["status"] == "todo"
    assert env["cli"] == "ollama serve"
    assert "https://ollama.com" in env["detail"]
    assert result.data["next"] == "environment"


def test_ollama_missing_binary_points_at_install(
    project_root, make_config, monkeypatch,
) -> None:
    monkeypatch.setattr(guide_mod, "ollama_state", lambda url: (False, []))
    monkeypatch.setattr("shutil.which", lambda name: None)
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root, provider=ProviderConfig(kind="ollama"))
    env = _steps(op_guide(cfg, GuideRequest()))["environment"]
    assert env["status"] == "todo"
    assert "not installed" in env["detail"]
    assert "https://ollama.com" in env["detail"]
    assert "ollama.com" in env["cli"]


def test_missing_model_gives_the_pull_command(project_root, make_config, monkeypatch) -> None:
    monkeypatch.setattr(guide_mod, "ollama_state", lambda url: (True, ["llama3.2:latest"]))
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root, provider=ProviderConfig(kind="ollama"))
    model = _steps(op_guide(cfg, GuideRequest()))["model"]
    assert model["status"] == "todo"
    assert model["cli"] == "ollama pull testmodel"


def test_installed_model_asks_for_a_smoke_test(project_root, make_config, monkeypatch) -> None:
    monkeypatch.setattr(guide_mod, "ollama_state", lambda url: (True, ["testmodel:latest"]))
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root, provider=ProviderConfig(kind="ollama"))
    model = _steps(op_guide(cfg, GuideRequest()))["model"]
    assert model["status"] == "todo"
    assert model["cli"] == "llm-localizator guide --smoke-test"


def test_smoke_test_marks_the_model_step_done(project_root, make_config, monkeypatch) -> None:
    monkeypatch.setattr(guide_mod, "ollama_state", lambda url: (True, ["testmodel"]))
    monkeypatch.setattr("llm_localizator.providers.build_provider", lambda *a, **k: NullProvider(handler=tagged))
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root, provider=ProviderConfig(kind="ollama"))
    result = op_guide(cfg, GuideRequest(smoke_test=True))
    assert _steps(result)["model"]["status"] == "done"
    marker = json.loads((cfg.state_root() / ".guide.json").read_text(encoding="utf-8"))
    assert marker["ok"] is True and marker["model"] == "testmodel"
    assert any("answered" in line for line in result.lines)


def test_smoke_test_refuses_paid_provider_without_yes(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root, provider=ProviderConfig(kind="anthropic"))
    result = op_guide(cfg, GuideRequest(smoke_test=True, skip_provider=True))
    assert any("paid cloud provider" in line for line in result.lines)
    assert not (cfg.state_root() / ".guide.json").exists()


def test_lines_render_a_checklist_with_the_next_command(
    project_root, make_config, monkeypatch,
) -> None:
    monkeypatch.setattr(
        "llm_localizator.projects.taskqueue.tq_available", lambda: False,
    )
    setup_project(project_root, {"a": "A"})
    lines = op_guide(make_config(project_root, translate_approach="local"), _req()).lines
    assert lines[0].startswith("[x] 1. Prepare your machine")
    assert any(line.startswith("Next: Translate") for line in lines)
    assert "  run: llm-localizator run-translate" in lines


@pytest.mark.parametrize("field", ["directory", "smoke_test", "skip_provider", "yes"])
def test_request_fields_have_cli_flags(field) -> None:
    from llm_localizator.cli.main import build_parser
    from llm_localizator.ops import build_commands_manifest

    dests = {f["name"] for f in build_commands_manifest(build_parser())["commands"]["guide"]["fields"]}
    assert field in dests
