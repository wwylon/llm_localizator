"""Read the hand-written ``## Winners`` table of a bakeoff REPORT.md (ADR-12).

Pure text in, text out. Nothing here writes configuration: a proposal is printed for a human
to paste, which is what keeps the model decision a human one.
"""

from __future__ import annotations

import re

__all__ = ["has_winner", "parse_winners", "propose_models_toml"]

_WINNER_RE = re.compile(r"(?im)^##\s+Winners\b")
_WINNER_ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*`?([^|`]+?)`?\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*)\|?\s*$",
)
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,119}$")
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def has_winner(text: str) -> bool:
    return _WINNER_RE.search(text) is not None


def parse_winners(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    in_table = False
    for line in text.splitlines():
        if _WINNER_RE.match(line.strip()):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table:
            continue
        if not line.startswith("|") or "---" in line or line.lower().startswith("| locale"):
            continue
        match = _WINNER_ROW_RE.match(line.strip())
        if not match:
            continue
        rows.append({
            "locale": match.group(1).strip(),
            "winner": match.group(2).strip(),
            "score": match.group(3).strip(),
            "runnerUp": match.group(4).strip(),
            "notes": match.group(5).strip(),
        })
    return rows


def propose_models_toml(
    text: str,
    locales: list[str],
    current: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """A ``[locales.models]`` snippet for ``locales`` plus notes about what was left out.

    Only locales the report names, with a plausible model tag, are proposed. Unchanged models
    are marked rather than dropped so the operator sees the whole picture. The fallback order
    is not recorded in the table (the runner-up cell is free text), so it is shown as a
    comment and never turned into configuration.
    """
    current = current or {}
    rows = {row["locale"]: row for row in parse_winners(text)}
    body: list[str] = []
    notes: list[str] = []
    for locale in locales:
        row = rows.get(locale)
        if row is None:
            notes.append(f"{locale}: not in the Winners table")
            continue
        model = row["winner"]
        if not _MODEL_RE.match(model):
            notes.append(f"{locale}: winner {model!r} is not a model tag; skipped")
            continue
        key = locale if _BARE_KEY_RE.match(locale) else f'"{locale}"'
        mark = "  # unchanged" if current.get(locale) == model else ""
        body.append(f'{key} = "{model}"{mark}')
        runner = row["runnerUp"]
        if runner:
            body.append(f"# {locale} runner-up: {runner}")
    toml = "[locales.models]\n" + "\n".join(body) + "\n" if body else ""
    return toml, notes
