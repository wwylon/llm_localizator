"""``bakeoff`` / ``run-bakeoff``: evidence for an ADR-12 model decision.

Translates a fixed key set with each candidate model and scores it by back-translation.
Local Ollama only. It writes a report and a ledger; it never changes ``[locales.models]``.
"""

from __future__ import annotations

from collections.abc import Callable

from ..catalog import catalog_for
from ..pipeline.bakeoff import (
    Cell,
    load_corpus_file,
    load_slice,
    plan_cells,
    run_bakeoff,
    sample_catalogue,
    stratify,
)
from ..pipeline.bakeoff_ledger import PINNED_MODELS
from ..projects import ProjectConfig
from ..projects.taskqueue import TaskqueueNotFound, submit, tq_available
from ..providers import Provider, ProviderError, build_provider
from .types import BakeoffRequest, OpResult
from ..projects.paths import project_path

__all__ = ["op_bakeoff", "DEFAULT_LIMIT"]

Reporter = Callable[[str], None]
DEFAULT_LIMIT = 30


def _fail(summary: str) -> OpResult:
    return OpResult(ok=False, exit_code=1, command="bakeoff", summary=summary)


def _installed(provider: Provider) -> list[str] | None:
    """Model tags the backend has, or ``None`` when it cannot say."""
    lister = getattr(provider, "available_models", None)
    if lister is None:
        return None
    try:
        return list(lister())
    except ProviderError:
        return None


def _is_installed(model: str, installed: list[str]) -> bool:
    from ..providers.ollama import model_installed

    return model_installed(model, installed)


def _select_keys(cfg: ProjectConfig, req: BakeoffRequest):
    limit = req.limit if req.limit else DEFAULT_LIMIT
    if getattr(req, "slice", None):
        return stratify(load_slice(req.slice), limit)
    if req.corpus == "builtin":
        return stratify(load_corpus_file(None), limit)
    if req.corpus:
        return stratify(load_corpus_file(project_path(cfg.root, req.corpus)), limit)
    catalog = catalog_for(cfg)
    return sample_catalogue(cfg, catalog, limit)


def _submit_job(cfg: ProjectConfig, req: BakeoffRequest, locales: list[str]) -> OpResult:
    overrides = {"--locales": ",".join(locales)}
    if req.models:
        overrides["--models"] = ",".join(req.models)
    if req.limit:
        overrides["--limit"] = str(req.limit)
    if req.corpus:
        overrides["--corpus"] = req.corpus
    if getattr(req, "slice", None):
        overrides["--slice"] = req.slice
    if req.family:
        overrides["--family"] = req.family
    if req.matrix:
        overrides["--matrix"] = "true"
    if req.force_cells:
        overrides["--force-cells"] = "true"
    try:
        outcome = submit(cfg, "bakeoff", overrides)
    except (TaskqueueNotFound, ValueError) as exc:
        return _fail(str(exc))
    return OpResult(
        ok=outcome.ok,
        exit_code=outcome.exit_code,
        command="bakeoff",
        summary=outcome.message,
        lines=[outcome.message] if outcome.message else [],
        data={"submitted": outcome.ok, "taskIds": list(outcome.task_ids)},
    )


def _propose_config(cfg: ProjectConfig, req: BakeoffRequest) -> OpResult:
    """Print a ``[locales.models]`` snippet from the report's Winners table. Writes nothing."""
    from ..pipeline.bakeoff_report import has_winner, propose_models_toml

    out_dir = project_path(cfg.root, req.out) or cfg.state_root() / "bakeoff"
    path = out_dir / "REPORT.md"
    if not path.is_file():
        return _fail(f"no report at {path}: run a bakeoff, or point --out at the folder with REPORT.md")
    text = path.read_text(encoding="utf-8")
    if not has_winner(text):
        return _fail(f"{path.name} has no '## Winners' section: write the Winner note first (ADR-12)")
    locales = list(req.locales) if req.locales else list(cfg.active_targets())
    current = dict(cfg.models or {})
    toml, notes = propose_models_toml(text, locales, current)
    if not toml:
        return _fail("; ".join(notes) or "no locale in the Winners table matches this project")
    lines = ["# Proposal only. Review it, then paste into .llm-localize.toml yourself (ADR-12).", *toml.splitlines()]
    lines += [f"# note: {n}" for n in notes]
    return OpResult(
        ok=True, exit_code=0, command="bakeoff",
        summary="proposal printed; nothing was written and [locales.models] is unchanged (ADR-12)",
        lines=lines, data={"toml": toml, "notes": notes, "report": str(path)},
    )


def op_bakeoff(
    cfg: ProjectConfig,
    req: BakeoffRequest,
    *,
    provider: Provider | None = None,
    report: Reporter | None = None,
) -> OpResult:
    if req.propose_config:
        return _propose_config(cfg, req)
    locales = list(req.locales) if req.locales else list(cfg.active_targets()[:1])
    if not locales:
        return _fail("no target locales: add one with `llm-localizator add-locale`")
    if provider is None and not req.dry_run and cfg.provider.kind != "ollama":
        return _fail(
            f"bakeoff compares local Ollama models; this project uses provider "
            f"{cfg.provider.kind!r}. Cloud models are out of scope (ADR-35)."
        )

    # Prefer the queue when tq is present; without it, run locally (engine works alone).
    if not req.dry_run and tq_available() and (req.submit or not req.inline):
        return _submit_job(cfg, req, locales)

    try:
        keys = _select_keys(cfg, req)
    except (OSError, ValueError) as exc:
        return _fail(str(exc))
    if not keys:
        return _fail("no source keys to test: the catalogue is empty (try --corpus builtin)")

    backend = provider or build_provider(cfg.provider)
    installed = None if req.dry_run and provider is None else _installed(backend)
    requested = list(req.models) if req.models else list(PINNED_MODELS)
    models = requested
    skipped_models: list[str] = []
    if installed:
        models = [m for m in requested if _is_installed(m, installed)]
        skipped_models = [m for m in requested if m not in models]

    cells = plan_cells(cfg, models, locales, matrix=req.matrix, family=req.family)
    if installed:
        cells = [c for c in cells if _is_installed(c.model, installed)]
    lines = [f"skip: model not installed locally: {m}" for m in skipped_models]
    lines += [_describe(cell) for cell in cells]
    plan_data = {
        "cells": [
            {"model": c.model, "locale": c.locale, "mode": c.mode, "family": c.family}
            for c in cells
        ],
        "keys": len(keys),
        "slice": getattr(req, "slice", None),
    }
    if not cells:
        return _fail("none of the requested models are installed")
    if req.dry_run:
        return OpResult(
            ok=True, exit_code=0, command="bakeoff",
            summary=f"{len(cells)} cell(s) × {len(keys)} key(s); nothing was run",
            lines=lines, data=plan_data,
        )

    out_dir = project_path(cfg.root, req.out) or cfg.state_root() / "bakeoff"
    outcome = run_bakeoff(
        cfg, backend, cells, keys,
        out_dir=out_dir, matrix=req.matrix, force_cells=req.force_cells,
        slice_name=getattr(req, "slice", None),
        report=report or print,
    )
    passed = sum(1 for r in outcome.results if r.gate_ok)
    lines += [
        f"{r.cell.model} {r.cell.locale} [{r.cell.mode}/{r.cell.family}] "
        f"mean={r.mean:.3f} gate={'PASS' if r.gate_ok else 'FAIL'}"
        for r in outcome.results
    ]
    if outcome.report_path:
        lines.append(f"report: {outcome.report_path}")
    return OpResult(
        ok=True, exit_code=0, command="bakeoff",
        summary=(
            f"ran {len(outcome.results)} cell(s), skipped {len(outcome.skipped)} already done; "
            f"{passed} passed the gate. Evidence only: [locales.models] is unchanged (ADR-12)."
        ),
        lines=lines,
        data={
            **plan_data,
            "ran": len(outcome.results),
            "skipped": len(outcome.skipped),
            "passed": passed,
            "outDir": str(out_dir),
        },
    )


def _describe(cell: Cell) -> str:
    return f"{cell.model} · {cell.locale} · {cell.mode}/{cell.family}"
