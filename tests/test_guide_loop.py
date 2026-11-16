"""The interactive ``guide`` loop, with scripted answers."""

from __future__ import annotations

from collections import deque

import pytest

from llm_localizator.cli import cmd_guide, cmd_init
from llm_localizator.cli.main import build_parser
from llm_localizator.ops import guide as guide_mod
from llm_localizator.ops.init import op_init
from llm_localizator.ops.types import InitRequest
from llm_localizator.projects import load_config

from .conftest import write_json


def _script(*answers):
    queue = deque(answers)
    asked: list[str] = []

    def fake_input(prompt: str) -> str:
        asked.append(prompt)
        return queue.popleft()

    return fake_input, asked


def _args(tmp_path, *extra):
    return build_parser().parse_args(["guide", "--dir", str(tmp_path), *extra])


def _project(tmp_path, **init):
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})
    init.setdefault("approach", "local")  # the steps after the approach choice (ADR-123)
    assert op_init(InitRequest(directory=str(tmp_path), no_register=True, **init)).ok
    return tmp_path


@pytest.fixture
def main_calls(monkeypatch):
    calls: list[list[str]] = []

    def fake_main(argv=None):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr("llm_localizator.cli.main.main", fake_main)
    return calls


def test_piped_guide_only_prints_and_never_prompts(tmp_path, capsys) -> None:
    _project(tmp_path, provider="null")

    def boom(_prompt: str) -> str:
        raise AssertionError("prompted")

    assert cmd_guide.run(_args(tmp_path, "--no-input"), input_fn=boom, interactive=False) == 0
    assert "Next: Choose languages" in capsys.readouterr().out


def test_loop_adds_a_language_then_offers_to_translate(tmp_path, capsys, main_calls) -> None:
    _project(tmp_path, provider="null")
    fake_input, asked = _script("pl, de", "y")
    code = cmd_guide.run(_args(tmp_path), input_fn=fake_input, interactive=True)
    assert code == 0
    assert load_config(tmp_path / ".llm-localize.toml").targets == ["pl", "de"]
    assert main_calls == [["run-translate", "--config", str(tmp_path / ".llm-localize.toml")]]
    assert "Translate now?" in asked[-1]
    assert "added pl (Polish)" in capsys.readouterr().out


def test_empty_answer_stops_the_loop(tmp_path, main_calls) -> None:
    _project(tmp_path, provider="null")
    fake_input, asked = _script("")
    assert cmd_guide.run(_args(tmp_path), input_fn=fake_input, interactive=True) == 0
    assert len(asked) == 1
    assert main_calls == []


def test_declining_translation_does_not_run_it(tmp_path, main_calls) -> None:
    _project(tmp_path, provider="null", targets=["pl"])
    fake_input, _asked = _script("n")
    assert cmd_guide.run(_args(tmp_path), input_fn=fake_input, interactive=True) == 0
    assert main_calls == []


def test_paid_provider_defaults_to_no(tmp_path, capsys, main_calls) -> None:
    _project(tmp_path, provider="anthropic", targets=["pl"])
    fake_input, _asked = _script("")
    cmd_guide.run(_args(tmp_path, "--skip-provider"), input_fn=fake_input, interactive=True)
    assert main_calls == []


def test_ollama_down_waits_and_q_stops(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(guide_mod, "ollama_state", lambda url: (False, []))
    _project(tmp_path, targets=["pl"])
    fake_input, asked = _script("q")
    assert cmd_guide.run(_args(tmp_path), input_fn=fake_input, interactive=True) == 0
    assert "Start Ollama" in asked[0]


def test_missing_model_offers_to_pull_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(guide_mod, "ollama_state", lambda url: (True, ["other:latest"]))
    monkeypatch.setattr(cmd_guide.shutil, "which", lambda name: "/usr/bin/ollama")
    ran: list[list[str]] = []
    monkeypatch.setattr(cmd_guide, "_run_command", lambda command: ran.append(command) or 0)
    _project(tmp_path, targets=["pl"], model="qwen2.5:7b")
    fake_input, _asked = _script("y", "n")
    cmd_guide.run(_args(tmp_path), input_fn=fake_input, interactive=True)
    assert ran == [["ollama", "pull", "qwen2.5:7b"]]


def test_fresh_folder_creates_the_project_then_continues(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "_home"))
    monkeypatch.setattr(cmd_init, "ollama_state", lambda url: (False, []))
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})
    # create config? yes | source | targets | model | domain | approach | run test translation? no
    fake_input, asked = _script("", "en", "pl", "", "", "local", "n")
    code = cmd_guide.run(
        _args(tmp_path, "--skip-provider"), input_fn=fake_input, interactive=True,
    )
    assert code == 0
    cfg = load_config(tmp_path / ".llm-localize.toml")
    assert cfg.targets == ["pl"]
    assert "quick test translation" in asked[-1]


def test_smoke_test_answer_marks_the_model_step_done(tmp_path, monkeypatch, capsys) -> None:
    from llm_localizator.providers import NullProvider

    from .conftest import tagged

    monkeypatch.setattr("llm_localizator.providers.build_provider", lambda *a, **k: NullProvider(handler=tagged))
    _project(tmp_path, targets=["pl"])
    fake_input, _asked = _script("y", "n")
    cmd_guide.run(_args(tmp_path, "--skip-provider"), input_fn=fake_input, interactive=True)
    out = capsys.readouterr().out
    assert "answered" in out
    assert "[x] 5. Pick a model and test it" in out


def test_eof_ends_the_guide_cleanly(tmp_path, capsys) -> None:
    _project(tmp_path, provider="null")

    def eof(_prompt: str) -> str:
        raise cmd_guide.PromptAborted

    assert cmd_guide.run(_args(tmp_path), input_fn=eof, interactive=True) == 0
    assert "Stopped." in capsys.readouterr().out


def test_eof_during_init_writes_nothing(tmp_path, capsys) -> None:
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})

    def eof(_prompt: str) -> str:
        raise cmd_guide.PromptAborted

    args = build_parser().parse_args(["init", str(tmp_path), "--no-register"])
    assert cmd_init.run(args, input_fn=eof, interactive=True) == 1
    assert not (tmp_path / ".llm-localize.toml").exists()
    assert "init --yes" in capsys.readouterr().out


def test_a_pipe_is_never_interactive(monkeypatch) -> None:
    from llm_localizator.cli.prompt import is_interactive

    class Tty:
        def isatty(self):
            return True

    class Pipe:
        def isatty(self):
            return False

    monkeypatch.setattr("sys.stdin", Tty())
    monkeypatch.setattr("sys.stdout", Pipe())
    assert is_interactive() is False
    monkeypatch.setattr("sys.stdout", Tty())
    assert is_interactive() is True


def test_approach_step_lists_the_options_and_records_the_choice(tmp_path, capsys) -> None:
    _project(tmp_path, provider="null", approach=None)
    fake_input, asked = _script("human", "")
    cmd_guide.run(_args(tmp_path, "--skip-provider"), input_fn=fake_input, interactive=True)
    out = capsys.readouterr().out
    assert "Next: Choose how to localize" in out
    for option in ("local:", "cloud:", "agent:", "human:", "hybrid:"):
        assert option in out
    assert "How do you want to localize" in asked[0]
    assert load_config(tmp_path / ".llm-localize.toml").translate_approach == "human"
