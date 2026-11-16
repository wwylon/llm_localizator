"""``init``: interactive prompts, flags, essentials-only config, actionable errors."""

from __future__ import annotations

from collections import deque

import pytest

from llm_localizator.cli import cmd_init
from llm_localizator.cli.main import build_parser
from llm_localizator.ops.init import op_init
from llm_localizator.ops.types import InitRequest
from llm_localizator.projects import load_config

from .conftest import write_json


@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch):
    monkeypatch.setattr(cmd_init, "ollama_state", lambda url: (False, []))


def _project(tmp_path):
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})
    return tmp_path


def _args(tmp_path, *extra):
    return build_parser().parse_args(["init", str(tmp_path), "--no-register", *extra])


def _script(*answers):
    queue = deque(answers)
    asked: list[str] = []

    def fake_input(prompt: str) -> str:
        asked.append(prompt)
        return queue.popleft()

    return fake_input, asked


def test_interactive_session_writes_the_answers(tmp_path, capsys) -> None:
    _project(tmp_path)
    fake_input, asked = _script("en", "pl, de", "qwen2.5:7b", 'a "quoted" product', "hybrid")
    code = cmd_init.run(_args(tmp_path), input_fn=fake_input, interactive=True)
    assert code == 0
    cfg = load_config(tmp_path / ".llm-localize.toml")
    assert cfg.targets == ["pl", "de"]
    assert cfg.model_for("pl") == "qwen2.5:7b"
    assert cfg.domain == 'a "quoted" product'
    assert cfg.translate_approach == "hybrid"
    assert len(asked) == 5
    out = capsys.readouterr().out
    assert "Polish" in out and "llm-localizator guide" in out


def test_flags_skip_their_prompts(tmp_path) -> None:
    _project(tmp_path)
    fake_input, asked = _script("en")
    args = _args(tmp_path, "--targets", "pl", "--model", "m1", "--domain", "a shop",
                 "--approach", "agent")
    assert cmd_init.run(args, input_fn=fake_input, interactive=True) == 0
    assert len(asked) == 1
    cfg = load_config(tmp_path / ".llm-localize.toml")
    assert (cfg.targets, cfg.model_for("pl"), cfg.domain) == (["pl"], "m1", "a shop")
    assert cfg.translate_approach == "agent"


def test_enter_accepts_defaults_and_leaves_targets_empty(tmp_path, capsys) -> None:
    _project(tmp_path)
    fake_input, _asked = _script("", "", "", "", "")
    assert cmd_init.run(_args(tmp_path), input_fn=fake_input, interactive=True) == 0
    cfg = load_config(tmp_path / ".llm-localize.toml")
    assert cfg.targets == []
    assert cfg.model_for("pl") == "llama3.2"
    assert "add-locale --locale pl" in capsys.readouterr().out


def test_non_interactive_never_prompts(tmp_path) -> None:
    _project(tmp_path)

    def boom(_prompt: str) -> str:
        raise AssertionError("prompted")

    assert cmd_init.run(_args(tmp_path, "--yes"), input_fn=boom) == 0


def test_existing_locales_become_targets_by_default(tmp_path) -> None:
    _project(tmp_path)
    write_json(tmp_path / "messages" / "de" / "app.json", {"a": "A"})
    assert op_init(InitRequest(directory=str(tmp_path), no_register=True)).ok
    assert load_config(tmp_path / ".llm-localize.toml").targets == ["de"]


def test_source_language_is_dropped_from_targets(tmp_path) -> None:
    _project(tmp_path)
    result = op_init(InitRequest(
        directory=str(tmp_path), no_register=True, targets=["en", "pl", "pl"],
    ))
    assert result.ok
    assert load_config(tmp_path / ".llm-localize.toml").targets == ["pl"]


def test_invalid_target_is_a_usage_error(tmp_path) -> None:
    _project(tmp_path)
    result = op_init(InitRequest(directory=str(tmp_path), no_register=True, targets=["../x"]))
    assert not result.ok and result.exit_code == 64
    assert not (tmp_path / ".llm-localize.toml").exists()


def test_generated_config_is_commented_essentials(tmp_path) -> None:
    _project(tmp_path)
    op_init(InitRequest(directory=str(tmp_path), no_register=True, targets=["pl"]))
    text = (tmp_path / ".llm-localize.toml").read_text(encoding="utf-8")
    assert "Run: llm-localizator guide" in text
    assert "llm-localizator add-locale --locale pl" in text
    assert text.count("[") < 12


def test_cloud_provider_config_has_no_ollama_url(tmp_path) -> None:
    _project(tmp_path)
    op_init(InitRequest(directory=str(tmp_path), no_register=True, provider="anthropic"))
    text = (tmp_path / ".llm-localize.toml").read_text(encoding="utf-8")
    assert 'kind = "anthropic"' in text
    assert "11434" not in text


def test_detection_failure_lists_layouts_and_an_example(tmp_path) -> None:
    result = op_init(InitRequest(directory=str(tmp_path), no_register=True))
    assert not result.ok
    blob = "\n".join(result.lines)
    assert "Supported layouts" in blob
    assert "messages/{locale}/{namespace}.json" in blob
    assert "llm-localizator init --format json-flat --path" in blob


def test_format_without_path_shows_the_fix(tmp_path) -> None:
    result = op_init(InitRequest(directory=str(tmp_path), catalog_format="po"))
    assert result.exit_code == 64
    assert "--format po --path" in "\n".join(result.lines)


def test_force_really_overwrites_an_existing_config(tmp_path) -> None:
    _project(tmp_path)
    assert op_init(InitRequest(directory=str(tmp_path), no_register=True, targets=["pl"])).ok
    assert load_config(tmp_path / ".llm-localize.toml").targets == ["pl"]
    assert not op_init(InitRequest(directory=str(tmp_path), no_register=True)).ok
    again = op_init(InitRequest(
        directory=str(tmp_path), no_register=True, force=True, targets=["de"],
    ))
    assert again.ok
    assert load_config(tmp_path / ".llm-localize.toml").targets == ["de"]
