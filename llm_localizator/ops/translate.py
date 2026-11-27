"""Translate operation."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from ..catalog import FlagStore, catalog_for
from ..pipeline.translate import run_translation
from ..projects import ProjectConfig
from ..projects.taskqueue import TaskqueueNotFound, tq_available

# Matches generate_blueprint's default; only a different value is a per-run option.
DEFAULT_BATCH_SIZE = 10
from .enqueue import enqueue_namespace_jobs
from .queue_policy import should_enqueue
from ..providers import provider_for_locale
from ..providers.preflight import check_ollama_model
from .types import DocumentsRequest, OpResult, TranslateRequest, resolve_namespaces

Reporter = Callable[[str], None]


def _submit(cfg: ProjectConfig, req: TranslateRequest) -> OpResult:
    """Enqueue translate for an operator-initiated request.

    Operator runs bypass ``[translate] min_keys`` (that floor is for automated
    sync→translate chains): per-locale blueprints bake ``--ignore-min-keys``,
    and one-off runs (any per-run option below) add it too. A plain request
    retries the shared per-locale tasks, so nothing can be dropped on the way.
    """
    overrides: dict[str, str] = {}
    if req.model:
        overrides["--model"] = req.model
    if req.batch_size and req.batch_size != DEFAULT_BATCH_SIZE:
        overrides["--batch-size"] = str(req.batch_size)
    if req.keys:
        overrides["--keys"] = ",".join(req.keys)
    for flag, value in (
        ("force", req.force), ("flagged", req.flagged),
        ("only_missing", getattr(req, "only_missing", False)),
        ("sync", getattr(req, "sync", False)),
        ("dry_run", req.dry_run), ("pre_translate", req.pre_translate),
        ("icu_only", getattr(req, "icu_only", False)), ("plain_only", getattr(req, "plain_only", False)),
    ):
        if value:
            overrides[f"--{flag.replace('_', '-')}"] = "true"
    namespaces = resolve_namespaces(req.namespace, req.namespaces)
    locales = list(req.locales) if req.locales else list(cfg.active_targets())

    if req.flagged:
        only_keys = FlagStore(cfg.flags_path).grouped() if cfg.flags_path else {}
        if not only_keys:
            return OpResult(
                ok=True,
                exit_code=0,
                command="translate",
                summary="no flagged keys",
                lines=["(100%) No flagged keys - nothing to do."],
            )

    to_submit: list[str] = []
    warnings: list[str] = []
    for loc in locales:
        model = req.model or cfg.model_for(loc)
        model_err = check_ollama_model(cfg, model)
        if model_err:
            # The queued task has its own Ollama health gate and waits for it;
            # a slow or busy Ollama must not refuse the submission.
            warnings.append(f"warning: {model_err}")
        to_submit.append(loc)

    if not to_submit:
        return OpResult(
            ok=True,
            exit_code=0,
            command="translate",
            summary="nothing to submit",
            lines=["nothing to submit"],
            data={"submitted": False, "taskIds": []},
        )

    try:
        any_ok, messages, task_ids = enqueue_namespace_jobs(
            cfg, "translate", overrides, namespaces, locales=to_submit,
        )
        summary = messages[0] if messages else ""
        return OpResult(
            ok=any_ok,
            exit_code=0 if any_ok else 1,
            command="translate",
            summary=summary,
            lines=[*warnings, *messages],
            data={
                "submitted": any_ok,
                "taskIds": task_ids,
            },
        )
    except TaskqueueNotFound as exc:
        return OpResult(ok=False, exit_code=1, command="translate", summary=str(exc))


def op_translate(
    cfg: ProjectConfig,
    req: TranslateRequest,
    *,
    report: Reporter | None = None,
) -> OpResult:
    from .tags import apply_tags

    req, early = apply_tags(cfg, req, "translate")
    if early is not None:
        return early
    if req.sample:
        from dataclasses import replace

        from .layout_sample import layout_sample, parse_sample

        try:
            size = parse_sample(req.sample)
        except ValueError as exc:
            return OpResult(ok=False, exit_code=64, command="translate", summary=str(exc))
        req = replace(req, keys=layout_sample(cfg, size), sample=None)
    if req.collection and req.collection != "messages":
        from .documents import op_documents

        from ..projects.collections import get_collection

        try:
            coll = get_collection(cfg, req.collection)
        except ValueError as exc:
            return OpResult(ok=False, exit_code=64, command="translate", summary=str(exc))
        if coll.kind == "remote":
            from .content import op_content_translate
            return op_content_translate(cfg, req, coll.name, report=report)
        if coll.root is None:
            return OpResult(
                ok=False, exit_code=64, command="translate",
                summary=f"collection {coll.name!r} has no directory",
            )
        return op_documents(cfg, DocumentsRequest(
            locales=req.locales,
            doc_dir=str(coll.root),
            model=req.model,
            dry_run=req.dry_run,
            submit=req.submit or not req.dry_run,
        ))

    # Prefer taskqueue for real work when tq is available (ADR-15).
    blocked = _cloud_block(cfg, req)
    if blocked is not None and not req.dry_run:
        return blocked
    if not req.dry_run and should_enqueue(
        submit=req.submit, inline=req.inline, tq=tq_available(),
    ):
        return _submit(cfg, req)

    catalog = catalog_for(cfg)
    if req.model:
        # A copy: the web server shares one config between requests, and one request's model choice must not
        # become every later request's default.
        import copy

        cfg = copy.deepcopy(cfg)
        cfg.apply_model_override(req.model)

    only_keys = None
    if req.flagged:
        only_keys = FlagStore(cfg.flags_path).grouped() if cfg.flags_path else {}
        if not only_keys:
            return OpResult(
                ok=True,
                exit_code=0,
                command="translate",
                summary="no flagged keys",
                lines=["(100%) No flagged keys - nothing to do."],
            )

    locales = req.locales or list(cfg.active_targets())
    if not req.dry_run and locales:
        for loc in locales:
            model = req.model or cfg.model_for(loc)
            model_err = check_ollama_model(cfg, model)
            if model_err:
                return OpResult(
                    ok=False,
                    exit_code=1,
                    command="translate",
                    summary=model_err,
                    lines=[model_err],
                )

    provider = provider_for_locale(cfg, locales[0] if locales else "default")
    lines: list[str] = []

    def _report(msg: str) -> None:
        lines.append(msg)
        if report is not None:
            report(msg)

    if tq_available() is False and not req.dry_run:
        _report("taskqueue (tq) not on PATH — running translate locally.")

    _report(
        f"translate {'(dry-run) ' if req.dry_run else ''}"
        f"locales={','.join(locales)} batch_size={req.batch_size}"
        + (" force" if req.force else "")
    )

    if getattr(req, "sync", False):
        cfg = dataclasses.replace(cfg, budget_cloud_batch=False)
    result = run_translation(
        cfg,
        catalog,
        provider,
        locales=locales,
        namespaces=resolve_namespaces(req.namespace, req.namespaces),
        batch_size=req.batch_size,
        force=req.force,
        dry_run=req.dry_run,
        only_keys=only_keys,
        multi_sample=req.multi_sample,
        named_keys=list(req.keys) if req.keys else None,
        pre_translate=req.pre_translate,
        trigger="pre-translate" if req.pre_translate else "translate",
        # Operator-initiated (web / ops / local CLI fallback): never apply min_keys.
        ignore_min_keys=True,
        icu_only=bool(getattr(req, "icu_only", False)),
        plain_only=bool(getattr(req, "plain_only", False)),
        only_missing=bool(getattr(req, "only_missing", False)),
        report=_report,
    )
    summary = (
        f"written {result.written}/{result.total}, rejected {len(result.rejected)}"
        + (" (dry-run)" if req.dry_run else "")
        + (" (aborted)" if result.aborted else "")
    )
    return OpResult(
        ok=result.exit_code == 0,
        exit_code=result.exit_code,
        command="translate",
        summary=summary,
        lines=lines,
        data={
            "total": result.total,
            "written": result.written,
            "rejected": len(result.rejected),
            "skipped": len(result.skipped),
            "icuFailed": len(result.icu_failed),
            "aborted": result.aborted,
            "dryRun": req.dry_run,
        },
    )


def _cloud_block(cfg: ProjectConfig, req: TranslateRequest) -> OpResult | None:
    """Refuse a cloud run that has no key list or whose ceiling exceeds the budget."""
    from ..catalog.cloud_cost import paying_cloud_kind
    from .estimate_cost import op_estimate_cost
    from .types import EstimateCostRequest

    locales = list(req.locales) if req.locales else list(cfg.active_targets())
    if not any(paying_cloud_kind(cfg, loc) for loc in locales):
        return None
    mode = getattr(cfg, "budget_mode", "on_request") or "on_request"
    if mode == "on_request" and not req.keys:
        summary = (
            "cloud mode is on_request: pass --keys namespace.key "
            'or set [budget] mode = "dynamic"'
        )
        return OpResult(
            ok=False, exit_code=1, command="translate",
            summary=summary, lines=[summary],
        )
    quote = op_estimate_cost(cfg, EstimateCostRequest(
        locales=locales,
        namespace=req.namespace,
        namespaces=req.namespaces,
        keys=req.keys,
        batch_size=req.batch_size,
        collection=req.collection,
    ))
    if not quote.ok or (not quote.data.get("local") and not quote.data.get("allowed", False)):
        return OpResult(
            ok=False,
            exit_code=1,
            command="translate",
            summary=quote.summary,
            lines=quote.lines,
            data=quote.data,
        )
    return None
