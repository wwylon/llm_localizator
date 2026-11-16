"""Bakeoff ledger helpers — cell expansion, JSONL, LEDGER.md (hermetic)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "PINNED_MODELS",
    "CORPUS_VERSION",
    "PENDING_LOCALES",
    "matrix_cells",
    "resolve_models",
    "done_cell_keys",
    "cell_already_done",
    "cell_result_row",
    "append_jsonl",
    "load_jsonl",
    "format_ledger_md",
    "write_ledger",
]

# Default Ollama comparison set for --matrix (skip if not installed).
PINNED_MODELS: tuple[str, ...] = (
    "aya-expanse:8b",
    "qwen2.5:7b",
    "translategemma:4b",
    "llama3.2",
)

CORPUS_VERSION = "v1"

# Locales to show as not-yet-run until operators expand --locales.
PENDING_LOCALES: tuple[str, ...] = (
    "ar", "de", "fr", "it", "nl", "pt-PT", "pt-BR",
    "cs", "es", "ru", "tr", "ko", "th", "vi",
)


def matrix_cells() -> list[tuple[str, str]]:
    """Standard Ollama cells: (prompt_mode, family)."""
    return [
        ("stripped", "chat"),
        ("consumer", "chat"),
        ("consumer", "mt_chat"),
    ]


def done_cell_keys(rows: Iterable[dict[str, Any]]) -> set[tuple[str, str, str, str, str]]:
    """Return (model, provider, locale, prompt_mode, family) for completed cells."""
    out: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        out.add((
            str(row.get("model") or ""),
            str(row.get("provider") or "ollama"),
            str(row.get("locale") or ""),
            str(row.get("prompt_mode") or ""),
            str(row.get("family") or ""),
        ))
    return out


def cell_already_done(
    done: set[tuple[str, str, str, str, str]],
    *,
    model: str,
    provider: str,
    locale: str,
    prompt_mode: str,
    family: str,
) -> bool:
    return (model, provider, locale, prompt_mode, family) in done


def resolve_models(models_arg: str | None, *, matrix: bool) -> list[str]:
    """Resolve ``--models``; matrix default is the pinned quartet."""
    raw = (models_arg or "").strip()
    if not raw:
        return list(PINNED_MODELS) if matrix else ["qwen2.5:7b", "aya-expanse:8b"]
    if raw.lower() == "all":
        return ["all"]  # caller expands from Ollama list
    return [m.strip() for m in raw.split(",") if m.strip()]


def cell_result_row(
    *,
    model: str,
    provider: str,
    locale: str,
    prompt_mode: str,
    family: str,
    keys: int,
    mean: float,
    amin: float,
    reject_rate: float,
    glossary_rejects: int,
    wall: float,
    gate_ok: bool,
    accepted: int | None = None,
    corpus_version: str = CORPUS_VERSION,
    notes: str = "",
    run_date: str | None = None,
) -> dict[str, Any]:
    n_ok = accepted if accepted is not None else max(0, keys - int(round(reject_rate * keys)))
    keys_per_s = (n_ok / wall) if wall > 0 else 0.0
    return {
        "date": run_date or date.today().isoformat(),
        "model": model,
        "provider": provider,
        "locale": locale,
        "prompt_mode": prompt_mode,
        "family": family,
        "keys": keys,
        "corpus_version": corpus_version,
        "mean_bt": round(mean, 4),
        "min_bt": round(amin, 4),
        "reject_rate": round(reject_rate, 4),
        "glossary_rejects": glossary_rejects,
        "wall_s": round(wall, 1),
        "keys_per_s": round(keys_per_s, 3),
        "gate": "PASS" if gate_ok else "FAIL",
        "notes": notes,
    }


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Append one ledger row using the shared durable JSONL helper."""
    from ..catalog.jsonl import append_jsonl as _append

    _append(path, row)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Stream ledger rows without slurping the whole file as one string."""
    from ..catalog.jsonl import iter_jsonl_objects

    if not path.is_file():
        return []
    return [obj for obj, _raw in iter_jsonl_objects(path)]


def _latest_by_key(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last row per (model, provider, locale, prompt_mode, family)."""
    latest: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("model"),
            row.get("provider"),
            row.get("locale"),
            row.get("prompt_mode"),
            row.get("family"),
        )
        latest[key] = row
    return sorted(
        latest.values(),
        key=lambda r: (
            str(r.get("locale") or ""),
            str(r.get("model") or ""),
            str(r.get("prompt_mode") or ""),
            str(r.get("family") or ""),
        ),
    )


def format_ledger_md(
    rows: list[dict[str, Any]],
    *,
    pinned: tuple[str, ...] = PINNED_MODELS,
    pending_locales: tuple[str, ...] = PENDING_LOCALES,
    primary_locale: str = "pl",
) -> str:
    latest = _latest_by_key(rows)
    lines: list[str] = [
        "# Quality bakeoff ledger",
        "",
        "Long-term index of model × locale × prompt cells (quality + speed).",
        "Winner decisions stay in `REPORT.md` (ADR-12). Regenerated by",
        "`llm-localizator run-bakeoff` (or `run_bakeoff.py --write-ledger`) from `matrix_results.jsonl`.",
        "",
        f"Corpus version tag: `{CORPUS_VERSION}`. Rows with different `keys` "
        "counts are not directly comparable.",
        "",
        "## Coverage by locale",
        "",
        "| Model | " + primary_locale + " | " + " | ".join(pending_locales) + " |",
        "|-------|" + "---|" * (1 + len(pending_locales)),
    ]
    tested: dict[str, set[str]] = {}
    for row in latest:
        if row.get("provider") not in (None, "ollama", "ctranslate2"):
            continue
        model = str(row.get("model") or "")
        loc = str(row.get("locale") or "")
        tested.setdefault(model, set()).add(loc)

    coverage_models = list(pinned)
    for m in sorted(tested):
        if m not in coverage_models:
            coverage_models.append(m)

    for model in coverage_models:
        locs = tested.get(model, set())
        cells = ["yes" if primary_locale in locs else "—"]
        for loc in pending_locales:
            cells.append("yes" if loc in locs else "—")
        lines.append(f"| `{model}` | " + " | ".join(cells) + " |")

    lines.extend([
        "",
        "## Cells (latest per key)",
        "",
        "| date | model | provider | locale | prompt_mode | family | keys | mean_bt | "
        "reject | wall_s | keys/s | gate | notes |",
        "|------|-------|----------|--------|-------------|--------|------|---------|--------|--------|--------|------|-------|",
    ])
    for row in latest:
        lines.append(
            f"| {row.get('date', '')} | `{row.get('model', '')}` | "
            f"{row.get('provider', '')} | {row.get('locale', '')} | "
            f"{row.get('prompt_mode', '')} | {row.get('family', '')} | "
            f"{row.get('keys', '')} | {row.get('mean_bt', '')} | "
            f"{row.get('reject_rate', '')} | {row.get('wall_s', '')} | "
            f"{row.get('keys_per_s', '')} | {row.get('gate', '')} | "
            f"{row.get('notes', '')} |"
        )

    if not latest:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | — | no runs yet |")

    seen_locales = {str(row.get("locale") or "") for row in latest}
    still_pending = [loc for loc in pending_locales if loc not in seen_locales]
    pending_line = (
        "None. Every listed locale has a row."
        if not still_pending
        else "Not yet run in the matrix (expand with `--locales`): "
        + ", ".join(f"`{loc}`" for loc in still_pending) + "."
    )
    lines.extend([
        "",
        "## Pending locales",
        "",
        pending_line,
        "",
        "## Default Ollama comparison set",
        "",
    ])
    for m in pinned:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines)


def write_ledger(jsonl_path: Path, ledger_path: Path) -> None:
    rows = load_jsonl(jsonl_path)
    ledger_path.write_text(format_ledger_md(rows), encoding="utf-8")
