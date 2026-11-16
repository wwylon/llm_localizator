"""Status and translate for a remote content collection. Not the file catalogue."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from ..content.client import ContentAPIError, ContentClient, endpoint_from_env
from ..content.contract import classify
from ..content.translate import complete_unit, plan_writes, translation_body
from ..projects import ProjectConfig
from ..projects.taskqueue import TaskqueueNotFound, submit, tq_available
from ..providers import provider_for_locale
from ..providers.base import ProviderError
from .types import OpResult, TranslateRequest

Reporter = Callable[[str], None]


def _content_locales(cfg: ProjectConfig, explicit: list[str] | None) -> list[str]:
    """Catalogue targets plus the catalogue source.

    The source locale cannot also be a file-catalogue target, but a unit
    written in another language still needs a translation into it.
    """
    if explicit:
        return list(explicit)
    locales = list(cfg.targets)
    if cfg.source_locale not in locales:
        locales.insert(0, cfg.source_locale)
    return locales


def op_content_status(cfg: ProjectConfig, name: str, *, missing: bool = False) -> OpResult:
    try:
        units = _load()
    except (ContentAPIError, ValueError) as exc:
        return OpResult(ok=False, exit_code=1, command="status", summary=str(exc))

    locales = _content_locales(cfg, None)
    counts: Counter[str] = Counter()
    rows = []
    lines = [f"{name}: {len(units)} unit(s)"]
    for unit in units:
        cells = classify(unit, locales)
        for cell in cells:
            counts[cell.status] += 1
        rows.append({
            "id": unit.id,
            "source_locale": unit.source_locale,
            "source_text": unit.source_text,
            "translate": unit.translate,
            "cells": [{"locale": c.locale, "status": c.status, "locked": c.locked} for c in cells],
        })
        gaps = [c for c in cells if c.status in {"missing", "stale"}]
        if missing and not gaps:
            continue
        if not unit.translate:
            lines.append(f"  {unit.id}  source={unit.source_locale}  skipped")
            continue
        lines.append(f"  {unit.id}  source={unit.source_locale}")
        shown = gaps if missing else cells
        for cell in shown:
            lock = " (human lock)" if cell.locked and cell.status == "stale" else ""
            lines.append(f"    {cell.locale} {cell.status}{lock}")
    summary = (
        f"{name}: {len(units)} unit(s)  "
        + " ".join(f"{key}={counts[key]}" for key in ("missing", "stale", "machine", "human", "skipped", "source"))
    )
    lines.insert(1, summary)
    return OpResult(
        ok=True,
        exit_code=0,
        command="status",
        summary=summary,
        lines=lines,
        data={"kind": "remote", "collection": name, "counts": dict(counts), "units": rows},
    )


def op_content_translate(
    cfg: ProjectConfig,
    req: TranslateRequest,
    name: str,
    *,
    report: Reporter | None = None,
    provider=None,
    opener=None,
) -> OpResult:
    if req.submit and not req.dry_run and tq_available():
        from .translate import _cloud_block
        blocked = _cloud_block(cfg, req)
        if blocked is not None:
            return blocked
        return _queue(cfg, req, name)

    try:
        url, token = endpoint_from_env()
        client = ContentClient(url, token, opener=opener)
        units = client.list_units()
    except ContentAPIError as exc:
        return OpResult(ok=False, exit_code=1, command="translate", summary=str(exc))

    locales = _content_locales(cfg, list(req.locales) if req.locales else None)
    work = plan_writes(units, locales, force=req.force)
    if req.keys:
        wanted = set(req.keys)
        work = [(unit, cell) for unit, cell in work if unit.id in wanted]
    if not work:
        return OpResult(
            ok=True, exit_code=0, command="translate",
            summary=f"{name}: nothing to translate",
            lines=[f"{name}: nothing to translate"],
            data={"kind": "remote", "collection": name, "written": 0},
        )
    if req.dry_run:
        lines = [f"{name}: would translate {len(work)}"]
        lines.extend(f"  {unit.id} -> {cell.locale}  source={unit.source_locale}" for unit, cell in work)
        return OpResult(
            ok=True, exit_code=0, command="translate",
            summary=lines[0], lines=lines,
            data={"kind": "remote", "collection": name, "written": 0, "pending": len(work)},
        )

    written = 0
    failed = 0
    lines = []
    domain = cfg.domain or "text"
    from ..catalog.cloud_cost import (
        cloud_run_decision,
        paying_cloud_kind,
        resolve_translation_model,
    )
    from ..providers import record_provider_spend
    if not req.dry_run:
        from .translate import _cloud_block
        blocked = _cloud_block(cfg, req)
        if blocked is not None:
            return blocked
    for unit, cell in work:
        kind = cfg.provider_kind_for(cell.locale)
        cloud_kind = paying_cloud_kind(cfg, cell.locale)
        model = req.model or (
            resolve_translation_model(cfg, cell.locale, cloud_kind)
            if cloud_kind else cfg.model_for(cell.locale)
        )
        hold_id = None
        if cloud_kind and not req.dry_run:
            decision = cloud_run_decision(
                cfg, [cell.locale],
                {cell.locale: [unit.source_text or ""]},
                named_keys=req.keys,
                batch_size=1,
                enforce_keys=False,
            )
            if decision.refuse:
                lines.append(decision.message)
                failed += 1
                break
            hold_id = decision.hold_id
        backend = provider or provider_for_locale(cfg, cell.locale, report=report)
        try:
            text = complete_unit(backend, unit, cell.locale, model=model, domain=domain)
            if cloud_kind:
                record_provider_spend(cfg, backend, cell.locale, model=model)
            client.put_translation(unit.id, cell.locale, translation_body(
                unit, text, provider=kind, model=model,
            ))
        except (ProviderError, ContentAPIError) as exc:
            failed += 1
            lines.append(f"  FAIL {unit.id} -> {cell.locale}: {exc}")
            if report:
                report(lines[-1])
            continue
        finally:
            if hold_id:
                from ..catalog.budget import BudgetStore
                BudgetStore(cfg.budget_root()).release(hold_id)
        written += 1
        lines.append(f"  {unit.id} -> {cell.locale}")
    summary = f"{name}: wrote {written}, failed {failed}"
    return OpResult(
        ok=failed == 0,
        exit_code=0 if failed == 0 else 1,
        command="translate",
        summary=summary,
        lines=[summary, *lines],
        data={"kind": "remote", "collection": name, "written": written, "failed": failed},
    )


def _load():
    url, token = endpoint_from_env()
    return ContentClient(url, token).list_units()


def _queue(cfg: ProjectConfig, req: TranslateRequest, name: str) -> OpResult:
    overrides = {"--collection": name, "--ignore-min-keys": "true"}
    if req.locales:
        overrides["--locales"] = ",".join(req.locales)
    if req.keys:
        overrides["--keys"] = ",".join(req.keys)
    if req.model:
        overrides["--model"] = req.model
    if req.force:
        overrides["--force"] = "true"
    try:
        outcome = submit(cfg, "translate", overrides)
    except TaskqueueNotFound as exc:
        return OpResult(ok=False, exit_code=1, command="translate", summary=str(exc))
    return OpResult(
        ok=outcome.ok,
        exit_code=outcome.exit_code,
        command="translate",
        summary=outcome.message or f"queued {name}",
        data={"kind": "remote", "collection": name, "queued": list(outcome.task_ids)},
    )
