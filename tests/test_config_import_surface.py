"""Public import surface after the config / config_load split."""

from __future__ import annotations


def test_content_tiers_reexported_from_config() -> None:
    from llm_localizator.projects.config import _content_tiers
    from llm_localizator.projects.config_load import _content_tiers as load_impl

    assert _content_tiers is load_impl
    assert _content_tiers({"legal/**": "human"}, "cfg.toml") == {"legal/**": "human"}


def test_load_config_still_public() -> None:
    from llm_localizator.projects import config

    assert callable(config.load_config)
    assert callable(config.discover_config)
