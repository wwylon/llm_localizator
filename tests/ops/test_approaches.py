"""How a project can be localized: options, recommendation, guide adaptation (ADR-123)."""

from __future__ import annotations

import pytest

from llm_localizator.ops.approaches import APPROACHES, op_approach, recommend, wiring
from llm_localizator.ops.guide import op_guide
from llm_localizator.ops.types import GuideRequest
from llm_localizator.projects import load_config
from llm_localizator.projects.config import APPROACH_IDS, ConfigError

from tests.conftest import setup_project


def _steps(result) -> dict[str, dict]:
    return {s["id"]: s for s in result.data["steps"]}


def _req() -> GuideRequest:
    return GuideRequest(skip_provider=True, skip_validate=True)


def test_every_approach_is_described() -> None:
    assert tuple(a.id for a in APPROACHES) == APPROACH_IDS
    for a in APPROACHES:
        assert a.title and a.words and a.needs and a.cost and a.stamp and a.when and a.commands


@pytest.mark.parametrize("probes, expected", [
    ({"cloud_configured": True, "budget_usd": 20}, "cloud"),
    ({"cloud_configured": True, "budget_usd": 0}, "cloud"),
    ({"ollama": True, "taskqueue": True}, "local"),
    ({"ollama": None, "provider": "ollama"}, "local"),
    ({"ollama": False, "provider": "ollama"}, "agent"),
])
def test_recommendation(probes, expected) -> None:
    rec, reason = recommend(probes)
    assert rec == expected and reason


def test_new_project_is_asked_first(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"})
    result = op_guide(make_config(project_root), _req())
    step = _steps(result)["approach"]
    assert result.data["next"] == "approach"
    assert step["status"] == "todo"
    for approach_id in APPROACH_IDS:
        assert f"- {approach_id}:" in step["detail"]
    assert step["cli"].startswith("llm-localizator approach --set ")
    assert step["detail_key"] == "guide_approach_pick"


def test_agent_approach_skips_the_model_and_points_at_the_backlog(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"})
    steps = _steps(op_guide(make_config(project_root, translate_approach="agent"), _req()))
    assert steps["approach"]["status"] == "done"
    assert steps["environment"]["detail_key"] == "guide_env_not_needed"
    assert steps["model"]["status"] == "done"
    assert steps["translate"]["cli"] == "llm-localizator agent-backlog"


def test_human_and_cloud_translate_steps(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"})
    human = _steps(op_guide(make_config(project_root, translate_approach="human"), _req()))
    assert human["translate"]["cli"].startswith("llm-localizator export")
    cloud = _steps(op_guide(make_config(project_root, translate_approach="cloud"), _req()))
    assert cloud["translate"]["cli"] == "llm-localizator estimate-cost"


def test_set_records_the_choice_in_the_config(tmp_path) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text('{"a": "A"}', encoding="utf-8")
    toml = tmp_path / ".llm-localize.toml"
    toml.write_text('# keep me\n[project]\nname = "t"\nsource_locale = "en"\n[catalog]\n'
                    'format = "json-flat"\npath = "locales/{locale}.json"\n[locales]\n'
                    'targets = ["pl"]\n', encoding="utf-8")
    cfg = load_config(toml)
    listed = op_approach(cfg, skip_probe=True)
    assert listed.data["current"] is None and listed.data["recommended"] == "local"
    assert op_approach(cfg, set_to="hybrid", skip_probe=True).ok
    assert load_config(toml).translate_approach == "hybrid"
    assert "# keep me" in toml.read_text(encoding="utf-8")
    assert op_approach(cfg, set_to="robots", skip_probe=True).exit_code == 2


def test_invalid_approach_in_config_is_rejected(tmp_path) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text("{}", encoding="utf-8")
    toml = tmp_path / ".llm-localize.toml"
    toml.write_text('[project]\nname = "t"\n[catalog]\nformat = "json-flat"\n'
                    'path = "locales/{locale}.json"\n[translate]\napproach = "magic"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="approach"):
        load_config(toml)


def test_wiring_kinds(make_config, project_root) -> None:
    flat = make_config(project_root, catalog_format="json-flat", catalog_path="l/{locale}.json",
                       scan_adapter="raw-js")
    assert wiring(flat)["id"] == "vanilla"
    flat.web_runtime_path = "static/js"
    assert wiring(flat)["id"] == "runtime"
    assert wiring(make_config(project_root, scan_adapter="next-intl"))["id"] == "framework"
    assert wiring(None)["id"] == "unknown"
