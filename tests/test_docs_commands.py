"""Every ``llm-localizator ...`` command shown in the user docs must actually parse."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from functools import lru_cache

from llm_localizator.cli.main import build_parser as _build_parser

#: One parser per module (M5: parse_args does not mutate it; each case rebuilt ~200 subparsers).
build_parser = lru_cache(maxsize=1)(_build_parser)

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    "README.md", "llms.txt",
    "docs/getting-started.md", "docs/adding-a-language.md", "docs/adding_localization.md",
    "docs/web.md", "docs/cli.md", "docs/configuration.md",
    "docs/concepts.md", "docs/existing-project.md", "docs/troubleshooting.md",
    "docs/cost-and-budget.md", "docs/exit-codes.md", "docs/agent-contract.md",
    "docs/consumer-localization-checklist.md", "docs/ci.md",
    "llm_localizator/help/human.md", "llm_localizator/help/agent.md",
    *sorted(p.relative_to(Path(__file__).resolve().parents[1]).as_posix()
            for p in (Path(__file__).resolve().parents[1] / "llm_localizator" / "help" / "skills").glob("*.md")),
]
_FENCE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
_COMMAND = re.compile(r"(?<![\w/-])llm-localizator\s+([a-z][a-z-]*(?:\s.*)?)$")


def _commands(text: str) -> list[list[str]]:
    found: list[list[str]] = []
    for block in _FENCE.findall(text):
        for raw in block.splitlines():
            line = raw.strip().lstrip("-").strip()
            if line.startswith("#") or "pip install" in line or "llm-localizator @" in line:
                continue
            match = _COMMAND.search(line)
            if not match:
                continue
            rest = re.sub(r"\s+#.*$", "", match.group(1)).strip()
            # Stop at shell plumbing: a redirect, pipe or chain is not part of the command.
            rest = re.split(r"\s(?:>>?|\||&&|\|\|)\s", rest)[0].strip()
            try:
                found.append(shlex.split(rest))
            except ValueError:
                continue
    return found


def _cases() -> list[tuple[str, list[str]]]:
    cases: list[tuple[str, list[str]]] = []
    for name in DOCS:
        for argv in _commands((ROOT / name).read_text(encoding="utf-8")):
            cases.append((name, argv))
    return cases


def test_the_docs_show_commands() -> None:
    assert len(_cases()) >= 15


@pytest.mark.parametrize("doc, argv", _cases(), ids=lambda v: v if isinstance(v, str) else " ".join(v))
def test_documented_command_parses(doc, argv, capsys) -> None:
    try:
        build_parser().parse_args(argv)
    except SystemExit:  # argparse rejected it
        pytest.fail(f"{doc}: `llm-localizator {' '.join(argv)}` is not valid: {capsys.readouterr().err.strip()}")


def test_an_invalid_command_would_be_caught() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["init", "--no-such-flag"])
