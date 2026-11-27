"""In-package model bakeoff (ADR-12, ADR-51).

Translate a fixed key set with each candidate model, back-translate to score it, and
append the evidence to a report. The command produces evidence only: it never edits
``[locales.models]``, so the ADR-12 gate (a dated Winner note, a human decision) stays
with the operator.

Local Ollama models only. The provider is injected, so tests run it with ``NullProvider``.
"""

from __future__ import annotations

import json
import random
import re
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ..core.cldr import language_name
from ..core.quality import score_translation
from ..core.validate import validate_translation
from ..projects import ContextNotes, ProjectConfig, load_glossary
from ..projects.context import glossary_prompt_block
from ..providers import CompletionRequest, Provider, ProviderError
from ..reporting import log_heartbeat, report as default_report, report_metric, report_progress
from .bakeoff_ledger import (
    CORPUS_VERSION,
    append_jsonl,
    cell_already_done,
    cell_result_row,
    done_cell_keys,
    load_jsonl,
    matrix_cells,
    write_ledger,
)
from .prompts import BatchItem, _role_from_key, build_backtranslate_prompt, build_single_prompt
from .scoring import score_model_for
from ..catalog.io import read_json

__all__ = [
    "BUILTIN_CORPUS",
    "DISAMBIGUATION_CORPUS",
    "BAKEOFF_SLICES",
    "Cell",
    "CellResult",
    "BakeoffOutcome",
    "KeyRow",
    "load_corpus_file",
    "load_slice",
    "sample_catalogue",
    "stratify",
    "bucket_of",
    "plan_cells",
    "run_cell",
    "run_bakeoff",
    "format_section",
    "append_report_section",
]

BUILTIN_CORPUS = Path(__file__).with_name("bakeoff_corpus.json")
DISAMBIGUATION_CORPUS = Path(__file__).with_name("bakeoff_disambiguation.json")
#: Named bakeoff slices (ADR-159). ``None`` / empty = catalogue or ``--corpus``.
BAKEOFF_SLICES = frozenset({"disambiguation"})
GATE_MEAN = 0.70
#: A cell rejecting more than this share of keys cannot win (ADR-12 evidence).
GATE_REJECT_RATE = 0.20
SPOT_KEYS = (
    "acct.deleteTitle", "amb.board", "long.onboarding",
    "filterUntranslated", "modalAdd", "keepToast",
)
STRIPPED_DOMAIN = "a developer tool web UI"

Reporter = Callable[[str], None]


@dataclass(frozen=True)
class KeyRow:
    key: str
    source: str
    bucket: str = ""
    message_key: str = ""
    context: str = ""


@dataclass(frozen=True)
class Cell:
    model: str
    locale: str
    mode: str  # "stripped" | "consumer"
    family: str


@dataclass
class CellResult:
    cell: Cell
    mean: float
    lowest: float
    reject_rate: float
    wall: float
    keys_per_s: float
    accepted: int
    glossary_rejects: int
    gate_ok: bool
    provider_errors: int = 0
    out_map: dict[str, str] = field(default_factory=dict)


@dataclass
class BakeoffOutcome:
    results: list[CellResult] = field(default_factory=list)
    skipped: list[Cell] = field(default_factory=list)
    failed: list[Cell] = field(default_factory=list)  # every call errored; not ledgered
    keys_n: int = 0
    report_path: Path | None = None
    ledger_path: Path | None = None
    jsonl_path: Path | None = None


# ---------------------------------------------------------------------------
# Key selection
# ---------------------------------------------------------------------------

def load_corpus_file(path: Path | None = None) -> list[KeyRow]:
    """Rows from a corpus JSON (a list of ``key/source/bucket/message_key/context``)."""
    source = Path(path) if path else BUILTIN_CORPUS
    try:
        rows = read_json(source)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read corpus {source}: {exc}") from exc
    if not isinstance(rows, list):
        raise ValueError(f"corpus {source} must be a JSON list")
    out: list[KeyRow] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("key") or not row.get("source"):
            continue
        key = str(row["key"])
        out.append(KeyRow(
            key=key,
            source=str(row["source"]),
            bucket=str(row.get("bucket") or ""),
            message_key=str(row.get("message_key") or key),
            context=str(row.get("context") or ""),
        ))
    return out


def load_slice(name: str) -> list[KeyRow]:
    """Frozen bakeoff slice by name (ADR-159)."""
    key = (name or "").strip().lower()
    if key not in BAKEOFF_SLICES:
        raise ValueError(
            f"unknown bakeoff slice {name!r}; known: {', '.join(sorted(BAKEOFF_SLICES))}"
        )
    if key == "disambiguation":
        return load_corpus_file(DISAMBIGUATION_CORPUS)
    raise ValueError(f"unknown bakeoff slice {name!r}")


def stratify(rows: list[KeyRow], limit: int, seed: int = 0) -> list[KeyRow]:
    """Up to ``limit`` rows, taken round-robin across buckets in a fixed order.

    Deterministic for one seed, so two bakeoffs of the same project compare like with like.
    """
    if not limit or len(rows) <= limit:
        return list(rows)
    rng = random.Random(seed)
    buckets: dict[str, list[KeyRow]] = {}
    for row in rows:
        buckets.setdefault(row.bucket or "other", []).append(row)
    for name in buckets:
        rng.shuffle(buckets[name])
    order = sorted(buckets)
    picked: list[KeyRow] = []
    while len(picked) < limit and any(buckets.values()):
        for name in order:
            if buckets[name] and len(picked) < limit:
                picked.append(buckets[name].pop())
    return picked


_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def bucket_of(message_key: str) -> str:
    """UI role a key name implies. camelCase and snake_case keys count too."""
    words = _CAMEL_BOUNDARY.sub(" ", message_key)
    for separator in ("_", ".", "-"):
        words = words.replace(separator, " ")
    return _role_from_key(words) or "other"


def sample_catalogue(cfg: ProjectConfig, catalog, limit: int, seed: int = 0) -> list[KeyRow]:
    """The project's own source strings, bucketed by the UI role their key name implies."""
    notes = ContextNotes(cfg.context_dir)
    rows: list[KeyRow] = []
    for namespace in cfg.namespaces_for(catalog):
        source = catalog.load(cfg.source_locale, namespace)
        for key in sorted(source):
            text = source[key]
            if not isinstance(text, str) or not text.strip() or cfg.is_skipped(namespace, key):
                continue
            message_key = f"{namespace}.{key}" if namespace else key
            rows.append(KeyRow(
                key=message_key,
                source=text,
                bucket=bucket_of(message_key),
                message_key=message_key,
                context=notes.note(namespace, key) or "",
            ))
    return stratify(rows, limit, seed)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def plan_cells(
    cfg: ProjectConfig,
    models: list[str],
    locales: list[str],
    *,
    matrix: bool = False,
    family: str | None = None,
) -> list[Cell]:
    """Every (locale, mode, family, model) cell, always including the locale's incumbent."""
    cells: list[Cell] = []
    for locale in locales:
        incumbent = cfg.model_for(locale)
        roster = list(dict.fromkeys([*models, incumbent] if incumbent else models))
        if matrix:
            combos = list(matrix_cells())
        else:
            combos = [("consumer", family or cfg.prompt_family_for(locale))]
        for mode, fam in combos:
            for model in roster:
                cells.append(Cell(model=model, locale=locale, mode=mode, family=fam))
    return cells


# ---------------------------------------------------------------------------
# One cell
# ---------------------------------------------------------------------------

def run_cell(
    provider: Provider,
    cell: Cell,
    keys: list[KeyRow],
    *,
    cfg: ProjectConfig,
    glossary: dict[str, Any],
    score_model: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    report: Reporter = default_report,
) -> CellResult:
    """Translate every key with one model, back-translate, and score."""
    consumer = cell.mode == "consumer"
    language = language_name(cell.locale)
    domain = cfg.domain if consumer else STRIPPED_DOMAIN
    register = cfg.style_for(cell.locale)[0] if consumer else "informal"
    cell_glossary = glossary if consumer else {}
    block = glossary_prompt_block(cell_glossary, cell.locale, language) if consumer else ""
    bt_model = (score_model if consumer else None) or cell.model
    timeout = cfg.provider.timeout_single_s

    scores: list[float] = []
    out_map: dict[str, str] = {}
    rejects = glossary_rejects = provider_errors = 0
    started = time.perf_counter()
    label = f"{cell.model} {cell.locale} [{cell.mode}/{cell.family}]"
    with log_heartbeat(f"bakeoff {label}", interval_s=45.0, reporter=report):
        for index, row in enumerate(keys, start=1):
            if progress:
                progress(index - 1, len(keys))
            item = BatchItem(source=row.source)
            if consumer:
                item.message_key = row.message_key
                item.context = row.context
            prompt = build_single_prompt(
                item, language, domain, block, locale=cell.locale, register=register,
                family=cell.family,
            )
            try:
                raw = provider.complete(CompletionRequest(
                    prompt=prompt, model=cell.model, timeout_s=timeout,
                    source_texts=[row.source], target_locale=cell.locale,
                )).strip()
            except ProviderError as exc:
                report(f"  FAIL {cell.model}/{row.key}: {exc}")
                rejects += 1
                provider_errors += 1
                continue
            ok, reason = validate_translation(row.source, raw, cell.locale, cell_glossary)
            if not ok:
                rejects += 1
                if "glossary" in reason.lower() or "forbidden" in reason.lower():
                    glossary_rejects += 1
                continue
            try:
                back = provider.complete(CompletionRequest(
                    prompt=build_backtranslate_prompt(raw, language),
                    model=bt_model, timeout_s=timeout,
                )).strip()
            except ProviderError:
                back = None
            quality = score_translation(
                row.source, raw, cell.locale, cell_glossary, back_translated=back,
            )
            scores.append(quality.score)
            out_map[row.key] = raw

    wall = time.perf_counter() - started
    mean = statistics.fmean(scores) if scores else 0.0
    return CellResult(
        cell=cell,
        mean=mean,
        lowest=min(scores) if scores else 0.0,
        reject_rate=rejects / max(1, len(keys)),
        wall=wall,
        keys_per_s=(len(scores) / wall) if wall > 0 else 0.0,
        accepted=len(scores),
        glossary_rejects=glossary_rejects,
        provider_errors=provider_errors,
        gate_ok=(
            mean >= GATE_MEAN and glossary_rejects == 0
            and rejects / max(1, len(keys)) <= GATE_REJECT_RATE
        ),
        out_map=out_map,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def format_section(
    results: list[CellResult], *, locales: list[str], keys_n: int, matrix: bool,
    slice_name: str | None = None,
) -> str:
    """The body of one dated report section (a table per locale plus spot checks)."""
    slice_bit = f" · slice `{slice_name}`" if slice_name else ""
    lines = [
        f"Locales: {', '.join(f'`{loc}`' for loc in locales)} · keys: {keys_n} · "
        f"corpus `{CORPUS_VERSION}` · {'matrix' if matrix else 'consumer'}{slice_bit}",
        "",
        "**Note:** Prefer **consumer/chat** for a Winner. Speed = wall_s and keys/s. "
        "Do not swap TOML from stripped-only rankings (ADR-12/23).",
        "",
    ]
    by_locale: dict[str, list[CellResult]] = {}
    for result in results:
        by_locale.setdefault(result.cell.locale, []).append(result)
    for locale, rows in by_locale.items():
        lines += [
            f"### Locale `{locale}`", "",
            "| Model | provider | prompt_mode | family | mean BT | reject | wall (s) | keys/s | gate |",
            "|-------|----------|-------------|--------|---------|--------|----------|--------|------|",
        ]
        for r in rows:
            lines.append(
                f"| `{r.cell.model}` | ollama | {r.cell.mode} | {r.cell.family} | "
                f"{r.mean:.3f} | {r.reject_rate:.0%} | {r.wall:.1f} | {r.keys_per_s:.2f} | "
                f"{'PASS' if r.gate_ok else 'FAIL'} |"
            )
        lines.append("")
    lines += ["### Spot-check keys", ""]
    for r in results:
        for spot in SPOT_KEYS:
            if spot in r.out_map:
                lines.append(
                    f"- `{r.cell.model}` / `{r.cell.locale}` / `{r.cell.mode}` / "
                    f"`{r.cell.family}` / `{spot}`: {r.out_map[spot]!r}"
                )
    lines.append("")
    return "\n".join(lines)


def append_report_section(path: Path, section: str) -> None:
    """Append a dated matrix section. Everything above it, Winners included, is left alone."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        existing = path.read_text(encoding="utf-8").rstrip() + "\n\n"
    else:
        existing = "# Quality bakeoff report\n\n"
    banner = f"## Matrix run {date.today().isoformat()}\n\n{section.rstrip()}\n"
    path.write_text(existing + banner, encoding="utf-8")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def run_bakeoff(
    cfg: ProjectConfig,
    provider: Provider,
    cells: list[Cell],
    keys: list[KeyRow],
    *,
    out_dir: Path,
    matrix: bool = False,
    force_cells: bool = False,
    slice_name: str | None = None,
    report: Reporter = default_report,
) -> BakeoffOutcome:
    """Run every cell not already in ``matrix_results.jsonl``, appending as it goes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "matrix_results.jsonl"
    done = set() if force_cells else done_cell_keys(load_jsonl(jsonl))
    glossary = load_glossary(cfg.glossary_path) or {} if cfg.glossary_path else {}
    score_model = score_model_for(cfg)
    provider_name = getattr(provider, "kind", "") or "ollama"
    outcome = BakeoffOutcome(keys_n=len(keys), jsonl_path=jsonl)
    total = max(1, len(cells))
    dead_models: set[str] = set()  # circuit breaker: one silent cell sidelines the model
    loaded: str | None = None

    def unload(model: str | None) -> None:
        # Free VRAM before the next model loads, so two never thrash the GPU.
        stop = getattr(provider, "stop", None)
        if model and callable(stop):
            try:
                stop(model)
            except Exception:  # best effort; a failed unload must not end the run
                pass

    for index, cell in enumerate(cells):
        label = f"{cell.model} {cell.locale} [{cell.mode}/{cell.family}]"
        if cell.model in dead_models:
            outcome.failed.append(cell)
            report_progress(index + 1, total, f"skip {label} (model produced no answers earlier)")
            continue
        if cell_already_done(
            done, model=cell.model, provider=provider_name, locale=cell.locale,
            prompt_mode=cell.mode, family=cell.family,
        ):
            outcome.skipped.append(cell)
            report_progress(index + 1, total, f"skip {label} (already in the ledger; --force-cells)")
            continue
        if loaded and loaded != cell.model:
            unload(loaded)
        loaded = cell.model
        report_progress(index, total, f"start {label}")
        result = run_cell(
            provider, cell, keys, cfg=cfg, glossary=glossary, score_model=score_model,
            report=report,
        )
        if keys and result.provider_errors >= len(keys):
            # A model that never answered says nothing about quality; a ledgered
            # zero would also make the cell look "already done" on the next run.
            outcome.failed.append(cell)
            dead_models.add(cell.model)
            report(f"bakeoff: {label} produced no answers (provider errors); not ledgered")
            report_progress(index + 1, total, f"failed {label}")
            continue
        outcome.results.append(result)
        append_jsonl(jsonl, cell_result_row(
            model=cell.model, provider=provider_name, locale=cell.locale,
            prompt_mode=cell.mode, family=cell.family, keys=len(keys), mean=result.mean,
            amin=result.lowest, reject_rate=result.reject_rate,
            glossary_rejects=result.glossary_rejects, wall=result.wall,
            gate_ok=result.gate_ok, accepted=result.accepted,
        ))
        safe = cell.model.replace(":", "_").replace("/", "_")
        (out_dir / f"{safe}_{cell.locale}_{cell.mode}_{cell.family}.json").write_text(
            json.dumps(result.out_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        report_progress(index + 1, total, f"done {label}")
        report_metric(done=index + 1, total=total)
        report(
            f"bakeoff: {label} mean={result.mean:.3f} reject={result.reject_rate:.0%} "
            f"wall={result.wall:.0f}s gate={'PASS' if result.gate_ok else 'FAIL'}"
        )

    unload(loaded)

    if outcome.results:
        locales = list(dict.fromkeys(r.cell.locale for r in outcome.results))
        outcome.report_path = out_dir / "REPORT.md"
        append_report_section(
            outcome.report_path,
            format_section(
                outcome.results, locales=locales, keys_n=len(keys), matrix=matrix,
                slice_name=slice_name,
            ),
        )
    outcome.ledger_path = out_dir / "LEDGER.md"
    write_ledger(jsonl, outcome.ledger_path)
    return outcome
