"""ADR-48 status surface + V23 skip for unsegmented scripts."""

from __future__ import annotations

from llm_localizator.catalog.state import translation_status
from llm_localizator.core.hash import src_hash
from llm_localizator.core.validate import check_word_count_band


def test_legacy_human_agent_surfaces_as_agent() -> None:
    entry = {
        "status": "human",
        "provider": "agent",
        "model": "cursor-agent",
        "src_sha": src_hash("Hello"),
    }
    assert translation_status("Hello", "Cześć", entry) == "agent"


def test_legacy_human_import_surfaces_as_imported() -> None:
    entry = {
        "status": "human",
        "provider": "import",
        "model": "sheet",
        "src_sha": src_hash("Hello"),
    }
    assert translation_status("Hello", "Cześć", entry) == "imported"


def test_true_human_stays_human() -> None:
    entry = {
        "status": "human",
        "provider": "human",
        "model": "human",
        "src_sha": src_hash("Hello"),
    }
    assert translation_status("Hello", "Cześć", entry) == "human"


def test_v23_skips_unsegmented_chinese() -> None:
    source = "Please confirm your email address"
    zh = "请确认您的电子邮件地址"
    assert check_word_count_band(source, zh, "zh") is None
    assert check_word_count_band(source, "ok", "pl") is not None
