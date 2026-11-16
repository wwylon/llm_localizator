"""onboard (P5)."""

from __future__ import annotations

import json

from llm_localizator.ops.onboard import op_onboard
from llm_localizator.projects import load_config


def test_onboard_fresh_app(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "_home"))
    (tmp_path / "src" / "locales").mkdir(parents=True)
    (tmp_path / "src" / "locales" / "en.json").write_text(json.dumps({"a": "Save"}), encoding="utf-8")
    result = op_onboard(str(tmp_path), targets=["pl"], frozen=["zh", "ar"], approach="hybrid",
                        runtime_path="web/js", no_register=True)
    assert result.ok, result.lines
    cfg = load_config(tmp_path / ".llm-localize.toml")
    assert cfg.targets == ["pl", "zh", "ar"] and cfg.frozen == ["zh", "ar"]
    assert cfg.translate_approach == "hybrid" and cfg.web_runtime_path == "web/js"
    assert not (tmp_path / "web" / "js" / "i18n.js").exists()  # only with --install-runtime
    assert any("llm-localizator cycle" in line for line in result.lines)
    again = op_onboard(str(tmp_path), approach="agent", install_runtime=True)
    assert again.ok and load_config(tmp_path / ".llm-localize.toml").translate_approach == "agent"
    assert (tmp_path / "web" / "js" / "i18n.js").is_file()
