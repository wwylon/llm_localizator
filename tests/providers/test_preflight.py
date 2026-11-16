"""Preflight helpers for configured Ollama pins."""

from __future__ import annotations

from llm_localizator.providers.ollama import model_installed
from llm_localizator.providers.preflight import (
    configured_model_pins,
    missing_configured_models,
)


def test_model_installed_matches_latest_tag() -> None:
    assert model_installed("llama3.2", ["llama3.2:latest"])
    assert model_installed("qwen2.5:7b", ["qwen2.5:7b"])
    assert not model_installed("qwen2.5:14b", ["qwen2.5:7b"])
    assert model_installed("llama3.2", ["llama3.2:8b"])
    assert not model_installed("llama3.2", ["llama3.2:latest", "llama3.2:8b"])


def test_configured_pins_and_missing(make_config, project_root) -> None:
    from llm_localizator.projects.config import LocaleRole

    cfg = make_config(
        project_root,
        models={"default": "aya-expanse:8b", "ar": "qwen2.5:14b"},
        documents_model="qwen2.5:14b",
        improve_model="aya-expanse:8b",
        roles={
            "pl": LocaleRole(
                primary="aya-expanse:8b",
                secondary="madlad:3b",
                judge="qwen2.5:7b",
            ),
        },
    )
    pins = configured_model_pins(cfg)
    assert "aya-expanse:8b" in pins
    assert "qwen2.5:14b" in pins
    assert "madlad:3b" in pins
    assert "qwen2.5:7b" in pins
    missing = missing_configured_models(cfg, ["aya-expanse:8b", "qwen2.5:7b"])
    assert "qwen2.5:14b" in missing
    assert "madlad:3b" in missing
