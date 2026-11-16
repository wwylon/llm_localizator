"""Blueprint YAML stays valid for awkward names (M3: values were pasted between hand-written quotes)."""

from __future__ import annotations

import yaml

from llm_localizator.projects.taskqueue import generate_blueprint


def test_project_name_with_yaml_syntax_still_parses(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path, name='my app: "beta" #1', targets=["pl", "de"])
    for job in ("translate", "sync", "agent-hardcoded"):
        doc = yaml.safe_load(generate_blueprint(cfg, job, vram_overrides={"testmodel": 4.0}))
        assert doc["args"][1] == 'my app: "beta" #1'
        assert 'my app: "beta" #1' in doc["description"]


def test_simple_names_render_as_before(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path, name="bridge", targets=["pl", "de"])
    text = generate_blueprint(cfg, "translate", vram_overrides={"testmodel": 4.0})
    assert 'args:             [run-translate, bridge, --locales, "pl,de", --batch-size, "10"]' in text
    assert yaml.safe_load(text)["priority"] == 50
