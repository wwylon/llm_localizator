"""Partial [provider.options] must keep default num_gpu / temperature."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.projects.config import load_config


def test_partial_provider_options_keep_defaults(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "messages" / "en").mkdir(parents=True)
    (root / "messages" / "en" / "app.json").write_text('{"hi":"Hi"}\n', encoding="utf-8")
    (root / ".llm-localize.toml").write_text(
        """
[project]
name = "opts"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]

[provider]
kind = "ollama"
options = { top_p = 0.95 }
""",
        encoding="utf-8",
    )
    cfg = load_config(root / ".llm-localize.toml")
    assert cfg.provider.options["top_p"] == 0.95
    assert cfg.provider.options["num_gpu"] == 99
    assert cfg.provider.options["temperature"] == 0.1
