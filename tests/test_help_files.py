"""The packaged help files stay true to the code (ADR-121, ADR-123)."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from functools import lru_cache

from llm_localizator.cli.main import build_parser as _build_parser

#: One parser per module (M5: parse_args does not mutate it; each case rebuilt ~200 subparsers).
build_parser = lru_cache(maxsize=1)(_build_parser)
from llm_localizator.help import GUIDES, guide_path, guide_text
from llm_localizator.ops.approaches import APPROACHES
from llm_localizator.ops.skill import op_skill, skill_text

ROOT = Path(__file__).resolve().parents[1]
_FENCE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
_INLINE = re.compile(r"`llm-localizator ([a-z][a-z-]*)[^`]*`")
_LINK = re.compile(r"\]\(([^)#]+)(?:#[^)]*)?\)")


def _fenced_commands(text: str) -> list[list[str]]:
    out = []
    for block in _FENCE.findall(text):
        for raw in block.splitlines():
            line = raw.strip()
            if not line.startswith("llm-localizator "):
                continue
            rest = re.sub(r"\s+#.*$", "", line[len("llm-localizator "):]).strip()
            out.append(shlex.split(rest))
    return out


@pytest.mark.parametrize("name", GUIDES)
def test_every_fenced_command_parses(name: str) -> None:
    parser = build_parser()
    commands = _fenced_commands(guide_text(name))
    assert commands
    for argv in commands:
        parser.parse_args(argv)


@pytest.mark.parametrize("name", GUIDES)
def test_every_inline_command_exists(name: str) -> None:
    parser = build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    for command in set(_INLINE.findall(guide_text(name))):
        assert command in sub.choices, f"{name}.md names unknown command {command!r}"


@pytest.mark.parametrize("name", GUIDES)
def test_every_approach_is_listed(name: str) -> None:
    text = guide_text(name)
    for approach in APPROACHES:
        assert f"`{approach.id}`" in text, f"{name}.md does not list approach {approach.id}"


def test_agent_guide_keeps_its_hard_rules() -> None:
    text = guide_text("agent")
    assert "## 1. Hard rules" in text
    for must in ("Ask before changing a consumer repository", "status=human",
                 "Never put a QA marker locale", "taskqueue", "What stays literal"):
        assert must in text


def test_docs_links_to_the_guides_resolve() -> None:
    for doc in ("docs/agents.md", "docs/operator-guide.md", "README.md",
                "docs/consumer-localization-checklist.md"):
        path = ROOT / doc
        for target in _LINK.findall(path.read_text(encoding="utf-8")):
            if "://" in target:
                continue
            assert (path.parent / target).resolve().exists(), f"{doc}: broken link {target}"


def test_guide_files_ship_in_the_package() -> None:
    for name in GUIDES:
        assert guide_path(name).is_file()


def test_skill_install_and_check(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    assert op_skill(cfg, "check").exit_code == 1
    assert op_skill(cfg, "install").ok
    skill = tmp_path / ".claude" / "skills" / "llm-localizator" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\nname: llm-localizator\n")
    assert guide_text("agent") in text and text == skill_text()
    assert op_skill(cfg, "check").exit_code == 0
    skill.write_text(text + "\nlocal edit\n", encoding="utf-8")
    assert op_skill(cfg, "check").data["state"] == "outdated"
    skill.write_text("my own skill\n", encoding="utf-8")
    assert op_skill(cfg, "install").exit_code == 1
    assert op_skill(cfg, "install", force=True).ok


@pytest.mark.parametrize("name", GUIDES)
def test_generated_blocks_are_current(name: str) -> None:
    """C1 (ADR-136): run `llm-localizator help --regenerate` when this fails."""
    from llm_localizator.help.blocks import BLOCK, regenerate

    text = guide_text(name)
    assert BLOCK.search(text), f"{name}.md has no generated block"
    assert regenerate(text, name) == text, f"{name}.md is stale: llm-localizator help --regenerate"


def test_stale_block_is_detected() -> None:
    from llm_localizator.help.blocks import regenerate

    text = guide_text("human").replace("| V43 |", "| V99 |", 1)
    assert regenerate(text, "human") != text


def test_listed_codes_exist_in_the_registry() -> None:
    from llm_localizator.help.blocks import AGENT_CHECKS, HUMAN_CHECKS, check_registry

    registry = check_registry()
    assert set(HUMAN_CHECKS) | set(AGENT_CHECKS) <= set(registry)


def test_agent_guide_lists_every_command() -> None:
    parser = build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    text = guide_text("agent")
    for name in sub.choices:
        assert f"| `{name}` |" in text, f"agent.md command table lacks {name}"


def test_doctor_warns_on_an_outdated_skill(tmp_path, make_config) -> None:
    from llm_localizator.doctor import consumer_checks

    cfg = make_config(tmp_path)
    assert not [c for c in consumer_checks(cfg) if c.name == "skill"]  # none installed: silent
    assert op_skill(cfg, "install").ok
    skill = tmp_path / ".claude" / "skills" / "llm-localizator" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nold text\n", encoding="utf-8")
    (check,) = [c for c in consumer_checks(cfg) if c.name == "skill"]
    assert check.status == "warn"


@pytest.mark.slow
def test_guide_steps_point_at_a_section(tmp_path, make_config) -> None:
    from llm_localizator.ops.guide import GUIDE_SECTIONS, build_guide
    from llm_localizator.ops.types import GuideRequest

    cfg = make_config(tmp_path)
    steps = build_guide(tmp_path, cfg, GuideRequest(directory=str(tmp_path), skip_validate=True))
    for step in steps:
        if step.id in GUIDE_SECTIONS:
            guide, _, number = step.guide_section.partition("#")
            assert f"## {number}." in guide_text(guide), step.id
