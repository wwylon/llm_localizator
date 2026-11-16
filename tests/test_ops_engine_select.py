"""W4: the Operations form's one-run engine also prices the run (estimate-cost honours body.engine)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.projects.config import load_config

BASE = (
    '[project]\nname = "demo"\nsource_locale = "en"\n\n'
    '[catalog]\nformat = "json-flat"\npath = "{locale}.json"\n\n'
    '[locales]\ntargets = ["pl"]\n\n'
    '[locales.models]\ndefault = "aya-expanse:8b"\n\n'
    '[privacy]\nallow_cloud = true\n\n[budget]\nmonthly_usd = 5\n'
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("LLM_LOCALIZE_ENGINE", raising=False)
    (tmp_path / "en.json").write_text('{"hello": "Hello", "bye": "Goodbye"}', encoding="utf-8")
    (tmp_path / "pl.json").write_text("{}", encoding="utf-8")
    path = tmp_path / ".llm-localize.toml"
    path.write_text(BASE, encoding="utf-8")
    return path


@pytest.mark.parametrize("command", ["estimate-cost", "estimate_cost"])
def test_estimate_prices_the_engine_picked_for_the_run(project: Path, command: str) -> None:
    cfg = load_config(project)
    local = dispatch_op(cfg, command, {"locales": ["pl"]}, actor_role="Admin")
    assert local["ok"] and local["data"]["local"] is True
    cloud = dispatch_op(cfg, command, {"locales": ["pl"], "engine": "claude-haiku"}, actor_role="Admin")
    assert cloud["ok"], cloud
    # A local project with a cloud engine for this run must reach the cost prompt, not skip it.
    assert cloud["data"]["local"] is False


def test_operations_page_sends_engine_and_uses_a_modal() -> None:
    js = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "operations.js").read_text(
        encoding="utf-8")
    assert "window.confirm(line)" not in js
    assert 'data-field' in js and '"engine"' in js
    assert "op-cost-modal" in js
