"""Residual lanes (--icu-only / --plain-only) reach the CLI, the queued run and the pipeline."""

from __future__ import annotations

import pytest

from llm_localizator.cli.main import build_parser
from llm_localizator.ops import translate as op_mod
from llm_localizator.ops.types import TranslateRequest


@pytest.mark.parametrize("command", ["translate", "run-translate"])
def test_lane_flags_parse_and_exclude_each_other(command: str) -> None:
    parser = build_parser()
    args = parser.parse_args([command, "--icu-only"])
    assert args.icu_only is True and args.plain_only is False
    with pytest.raises(SystemExit):
        parser.parse_args([command, "--icu-only", "--plain-only"])


def test_queued_translate_carries_the_lane(project_root, make_config, monkeypatch) -> None:
    from tests.conftest import setup_project

    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(project_root)
    seen: dict = {}

    def fake_enqueue(cfg_, job, overrides, namespaces, *, locales):
        seen.update(overrides)
        return True, ["queued"], ["t1"]

    monkeypatch.setattr(op_mod, "enqueue_namespace_jobs", fake_enqueue)
    monkeypatch.setattr(op_mod, "check_ollama_model", lambda *a, **k: None)
    op_mod._submit(cfg, TranslateRequest(locales=["pl"], plain_only=True))
    assert seen.get("--plain-only") == "true"
    assert "--icu-only" not in seen
