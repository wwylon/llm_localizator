"""Per-ecosystem and per-language help pages stay true to the code (ADR-139)."""

from __future__ import annotations

import re

import pytest

from llm_localizator.cli.main import build_parser
from llm_localizator.core.locales import profile
from llm_localizator.help.topics import (
    CODE_TOPICS, HELP_DIR, SCRIPT_GROUPS, UNPROFILED_GROUPS, code_text, code_topic_names, lang_text, lang_topic_names,
    regenerate_code,
)
from llm_localizator.scan.ecosystems import SINK_LABELS, ui_sink_before
from llm_localizator.scan.tiers import tier_for

_INLINE = re.compile(r"`llm-localizator ([a-z][a-z-]*)[^`]*`")


@pytest.mark.parametrize("name", code_topic_names())
def test_code_topic_has_both_sections_and_current_block(name: str) -> None:
    raw = (HELP_DIR / "code" / f"{name}.md").read_text(encoding="utf-8")
    assert "## For people" in raw and "## For agents" in raw
    assert regenerate_code(name, raw) == raw, f"run llm-localizator help --regenerate ({name})"
    for reader in ("human", "agent"):
        text = code_text(name, reader)
        assert CODE_TOPICS[name][0].split(" (")[0].split()[0]  # title exists
        assert ("## For agents" in text) == (reader == "agent")
        assert len(text) < 8000


@pytest.mark.parametrize("name", code_topic_names())
def test_code_topic_names_real_commands_and_tiers(name: str) -> None:
    parser = build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    raw = (HELP_DIR / "code" / f"{name}.md").read_text(encoding="utf-8")
    for command in set(_INLINE.findall(raw)):
        assert command in sub.choices, f"{name}.md names unknown command {command!r}"
    assert tier_for(CODE_TOPICS[name][1][0]) in {"supported", "basic"}


def test_sink_labels_match_the_sink_tables() -> None:
    literal = '"Some visible text here"'
    for lang_id, labels in SINK_LABELS.items():
        for label in labels:
            assert ui_sink_before(lang_id, f"{label} {literal}", literal), f"{lang_id}: {label}"


@pytest.mark.parametrize("code", lang_topic_names() + sorted(UNPROFILED_GROUPS))
def test_language_page_renders_for_both_readers(code: str) -> None:
    human, agent = lang_text(code, "human"), lang_text(code, "agent")
    assert human.startswith("# ") and agent.startswith("# ")
    assert "## Practice:" in human and "## Practice:" in agent
    assert "## For agents" not in human
    assert "## For people" not in agent


def test_every_script_group_has_a_page() -> None:
    groups = set(SCRIPT_GROUPS.values()) | set(UNPROFILED_GROUPS.values()) | {"other"}
    for group in groups:
        assert (HELP_DIR / "lang" / "groups" / f"{group}.md").exists(), group


def test_script_of_south_east_asian_profiles() -> None:
    assert (profile("km").script, profile("lo").script, profile("my").script) == ("khmer", "lao", "myanmar")
