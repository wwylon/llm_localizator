"""Generated blocks in the packaged guides (C1, ADR-136).

``human.md`` and ``agent.md`` keep their prose by hand. Three tables are rendered
from code so they cannot drift:

* ``approaches`` from ``ops/approaches.APPROACHES``;
* ``checks`` (V-codes) from the ``docs/checks.md`` registry: the code must exist
  there; the plain wording below is curated for each reader, and the agent table
  adds the command that fixes it;
* ``commands`` (agent guide) from ``cli.main.build_parser()``.

A block sits between ``<!-- generated:NAME -->`` and ``<!-- /generated:NAME -->``.
``llm-localizator help --regenerate`` rewrites them; ``tests/test_help_files.py``
fails when a block is stale. ``docs/checks.md`` is read from the repository, so
regeneration runs in a checkout, not from an installed wheel.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["BLOCK", "CHECKS_DOC", "check_registry", "render", "regenerate", "regenerate_files"]

BLOCK = re.compile(r"(<!-- generated:([a-z-]+) -->\n)(.*?)(<!-- /generated:\2 -->)", re.S)
CHECKS_DOC = Path(__file__).resolve().parents[2] / "docs" / "checks.md"
_ROW = re.compile(r'^\| <a id="v\d+"></a>(V\d+) \| (error|warning) \| ([^|]+) \|', re.M)

#: Codes each reader sees, with wording for that reader (meaning, fix command).
HUMAN_CHECKS: dict[str, str] = {
    "V01": "key missing in a language (for frozen languages this is expected)",
    "V03": "plural forms missing for the language (Polish needs one, few, many, other)",
    "V04": "a forbidden glossary variant was used, or a whole label lacks its approved word",
    "V13": "an approved glossary term is missing from a sentence (warning)",
    "V43": "the translation is wrapped in quotes",
    "V46": "a short label got a long sentence back (the model echoed its instructions)",
    "V47": "the ICU structure changed (a `select` became a `plural`, or a branch is gone)",
    "V48": "one glossary term is translated several ways across the app",
    "V49": "the app's description leaked into the translation",
    "V50": "markup the source lacks (`**`, backticks), or text moved outside an ICU message",
    "V51": "a leading symbol (`~`, `≈`, `<`) was dropped or spelled out",
}
AGENT_CHECKS: dict[str, tuple[str, str]] = {
    "V01": ("key missing in a target locale", "`translate`, or `agent-backlog` then `set`"),
    "V02": ("placeholder set differs from the source", "`set` with every `{placeholder}` kept"),
    "V03": ("plural categories missing for the locale", "`cycle --repair`, or `set` the full plural"),
    "V04": ("forbidden glossary variant, or a whole label lacks its approved word",
            "`set` the approved term"),
    "V13": ("approved glossary term absent (warning)", "`set` if the term belongs; else leave it"),
    "V27": ("HTML tag structure differs from the source", "`set` with the source tags"),
    "V43": ("translation wrapped in quotes", "`cycle --repair`, or `set` without the quotes"),
    "V46": ("leaked prompt text: a long answer to a short source", "`cycle --repair`; `set` a label"),
    "V47": ("ICU structure changed (`select` became `plural`, a branch lost)",
            "`cycle --repair`; `set` the source structure"),
    "V48": ("one glossary term rendered several ways", "`set` the approved rendering everywhere"),
    "V49": ("project description leaked into the output", "`cycle --repair`"),
    "V50": ("invented markup, or text moved outside an ICU message", "`set` the plain text"),
    "V51": ("leading symbol dropped or spelled out", "`set` with the symbol"),
}


def check_registry(path: Path = CHECKS_DOC) -> dict[str, tuple[str, str]]:
    """``{code: (severity, meaning)}`` from ``docs/checks.md``."""
    text = path.read_text(encoding="utf-8")
    return {m.group(1): (m.group(2), m.group(3).strip()) for m in _ROW.finditer(text)}


def _approaches(reader: str) -> list[str]:
    from ..ops.approaches import APPROACHES

    if reader == "human":
        rows = ["| Approach | Pick it when | Cost |", "|---|---|---|"]
        rows += [f"| `{a.id}`: {a.title} | {a.when} | {a.cost} |" for a in APPROACHES]
    else:
        rows = ["| id | Who writes the words | Needs | Stamp written |", "|---|---|---|---|"]
        rows += [f"| `{a.id}` | {a.words} | {a.needs} | {a.stamp} |" for a in APPROACHES]
    return rows


def _checks(reader: str, registry: dict[str, tuple[str, str]]) -> list[str]:
    wanted = HUMAN_CHECKS if reader == "human" else AGENT_CHECKS
    missing = sorted(set(wanted) - set(registry))
    if missing:
        raise ValueError(f"codes not in docs/checks.md: {', '.join(missing)}")
    if reader == "human":
        rows = ["| Code | Severity | What it means |", "|---|---|---|"]
        rows += [f"| {c} | {registry[c][0]} | {wanted[c]} |" for c in wanted]
    else:
        rows = ["| Code | Severity | Meaning | Fix with |", "|---|---|---|---|"]
        rows += [f"| {c} | {registry[c][0]} | {m} | {fix} |" for c, (m, fix) in wanted.items()]
    return rows


def _commands() -> list[str]:
    from ..cli.main import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    helps = {c.dest: (c.help or "").strip() for c in sub._choices_actions}
    rows = ["| Command | What it does |", "|---|---|"]
    for name in sorted(sub.choices):
        text = " ".join(helps.get(name, "").split()).replace("|", "/")
        rows.append(f"| `{name}` | {text} |")
    return rows


def render(name: str, reader: str, registry: dict[str, tuple[str, str]]) -> str:
    if name == "approaches":
        rows = _approaches(reader)
    elif name == "checks":
        rows = _checks(reader, registry)
    elif name == "commands":
        rows = _commands()
    else:
        raise ValueError(f"unknown generated block {name!r}")
    return "\n".join(rows) + "\n"


def regenerate(text: str, reader: str, registry: dict[str, tuple[str, str]] | None = None) -> str:
    """``text`` with every generated block re-rendered."""
    registry = check_registry() if registry is None else registry
    return BLOCK.sub(lambda m: m.group(1) + render(m.group(2), reader, registry) + m.group(4), text)


def regenerate_files() -> list[str]:
    """Rewrite both guides; the names of the files that changed."""
    from . import GUIDES, guide_path

    registry = check_registry()
    changed = []
    for name in GUIDES:
        path = guide_path(name)
        old = path.read_text(encoding="utf-8")
        new = regenerate(old, name, registry)
        if new != old:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed.append(path.name)
    from .topics import CODE_TOPICS, HELP_DIR, regenerate_code

    for topic in CODE_TOPICS:
        path = HELP_DIR / "code" / f"{topic}.md"
        if not path.exists():
            continue
        old = path.read_text(encoding="utf-8")
        new = regenerate_code(topic, old)
        if new != old:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed.append(f"code/{path.name}")
    return changed
