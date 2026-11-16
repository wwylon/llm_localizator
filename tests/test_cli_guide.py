"""``llm-localizator guide`` from the command line."""

from __future__ import annotations

import pytest
import json

from llm_localizator.cli.main import main

from .conftest import write_json


def test_guide_in_an_empty_folder_prints_a_checklist(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["guide", "--skip-provider"]) == 0
    out = capsys.readouterr().out
    assert "[ ] 2. Create the project" in out
    assert "Next: Create the project" in out
    assert "run: llm-localizator init" in out


def test_guide_json_is_machine_readable(tmp_path, capsys) -> None:
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})
    assert main(["guide", "--dir", str(tmp_path), "--skip-provider", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "guide"
    assert payload["data"]["next"] == "project"
    assert payload["data"]["hasConfig"] is False


@pytest.mark.slow
def test_guide_follows_an_initialised_project(tmp_path, capsys, monkeypatch) -> None:
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--no-register"]) == 0
    capsys.readouterr()
    assert main(["guide", "--skip-provider"]) == 0
    out = capsys.readouterr().out
    assert "[x] 2. Create the project" in out
    # The options come before anything else (ADR-123).
    assert "Next: Choose how to localize" in out
    for option in ("local:", "cloud:", "agent:", "human:", "hybrid:"):
        assert option in out
    assert main(["approach", "--set", "agent"]) == 0
    capsys.readouterr()
    assert main(["guide", "--skip-provider"]) == 0
    out = capsys.readouterr().out
    assert "[x] 3. Choose how to localize" in out
    assert "Next: Choose languages" in out
    assert "llm-localizator add-locale --locale pl" in out


def test_bare_command_keeps_exit_64_and_points_at_the_guide(capsys) -> None:
    assert main([]) == 64
    assert "New here? Run: llm-localizator guide" in capsys.readouterr().out
