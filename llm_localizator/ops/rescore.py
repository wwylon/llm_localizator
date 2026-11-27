"""Re-score existing translations with back-translation (no retranslation)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..catalog import ScoreStore, StateStore, build_catalog
from ..catalog.scores import quality_score_of, score_matches_text
from ..pipeline.run_manifest import RunManifest, config_fingerprint
from ..pipeline.scoring import PendingScoreItem, rescore_items, score_model_for
from ..projects import ProjectConfig, load_glossary
from ..projects.taskqueue import TaskqueueNotFound, tq_available
from .cloud_gate import cloud_session
from .enqueue import enqueue_namespace_jobs
from .queue_policy import should_enqueue
from ..providers import project_provider
from ..reporting import report_run_summary
from .types import OpResult, RescoreRequest, resolve_namespaces

Reporter = Callable[[str], None]


def _parse_iso(value: object):
    from datetime import datetime, timezone

    from ..catalog.state import parse_translated_at

    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = parse_translated_at(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _rescore_stale(
    score_row: dict | None,
    *,
    state_entry: dict | None,
    translated: str,
) -> bool:
    if score_row is None:
        return True
    if score_row.get("scorer") == "heuristic":
        return True
    if not score_matches_text(score_row, translated):
        return True
    scored_at = _parse_iso(score_row.get("scored_at"))
    translated_at = _parse_iso(
        state_entry.get("translated_at") if state_entry else None
    )
    if scored_at and translated_at and scored_at < translated_at:
        return True
    return False


def collect_rescore_items(
    cfg: ProjectConfig,
    catalog,
    state: StateStore,
    scores: ScoreStore,
    *,
    locales: list[str],
    namespaces: list[str],
    stale_only: bool = False,
    below_score: float | None = None,
    keys: list[str] | None = None,
) -> list[PendingScoreItem]:
    from ..pipeline.improve import parse_named_keys

    named = set(parse_named_keys(keys, namespaces)) if keys else None
    work: list[PendingScoreItem] = []
    for locale in locales:
        for ns in namespaces:
            source = catalog.load(cfg.source_locale, ns)
            target = catalog.load(locale, ns)
            for key, src in source.items():
                if cfg.is_skipped(ns, key, src):
                    continue
                if named is None and cfg.is_request_only(ns, key):
                    continue
                if named is not None and (ns, key) not in named:
                    continue
                text = target.get(key)
                if not text:
                    continue
                entry = state.entry(locale, ns, key)
                row = scores.get(locale, ns, key)
                if stale_only and not _rescore_stale(row, state_entry=entry, translated=text):
                    continue
                if below_score is not None:
                    score = quality_score_of(row if isinstance(row, dict) else None)
                    if score is None or score >= below_score:
                        continue
                work.append(PendingScoreItem(
                    locale=locale,
                    namespace=ns,
                    key=key,
                    source=src,
                    translated=text,
                ))
    return work


def execute_rescore(
    cfg: ProjectConfig,
    *,
    locales: list[str] | None = None,
    namespaces: list[str] | None = None,
    model: str | None = None,
    dry_run: bool = False,
    stale_only: bool = False,
    below_score: float | None = None,
    keys: list[str] | None = None,
    report: Reporter | None = None,
) -> OpResult:
    """Score existing catalogue strings; write ScoreStore (unless dry-run)."""
    if stale_only and below_score is None:
        return OpResult(
            ok=False,
            exit_code=1,
            command="rescore",
            summary="--stale-only requires --below-score (pair filters to avoid skipping fresh keys)",
        )
    work_cfg = replace(cfg, score_model=model) if model else cfg
    catalog = build_catalog(
        work_cfg.catalog_format, work_cfg.root, work_cfg.catalog_path, work_cfg.source_locale,
    )
    glossary = load_glossary(work_cfg.glossary_path)
    target_locales = locales or list(work_cfg.active_targets())
    ns_list = namespaces or work_cfg.namespaces_for(catalog)
    lines: list[str] = []

    def _report(msg: str) -> None:
        lines.append(msg)
        if report is not None:
            report(msg)

    _report(
        f"collecting keys for {len(target_locales)} locale(s), "
        f"{len(ns_list)} namespace(s)…"
    )
    state = StateStore(work_cfg.state_dir)
    scores = ScoreStore(work_cfg.scores_root())
    work = collect_rescore_items(
        work_cfg, catalog, state, scores,
        locales=target_locales,
        namespaces=ns_list,
        stale_only=stale_only,
        below_score=below_score,
        keys=keys,
    )

    unknown: list[str] = []
    if keys:
        from ..pipeline.improve import parse_named_keys

        found = {(i.namespace, i.key) for i in work}
        unknown = sorted(
            f"{ns}.{key}" for ns, key in set(parse_named_keys(keys, ns_list)) - found
        )
        if unknown:
            _report("unknown or not rescorable keys: " + ", ".join(unknown))

    total = len(work)
    _report(f"rescoring {total} key(s) across {len(target_locales)} locale(s)")
    if dry_run:
        for item in work[:80]:
            _report(f"  would rescore {item.locale}/{item.namespace}.{item.key}")
        if total > 80:
            _report(f"  … and {total - 80} more")
        return OpResult(
            ok=True,
            exit_code=0,
            command="rescore",
            summary=f"would re-score {total} key(s) (dry-run)",
            lines=lines[-80:] if len(lines) > 80 else lines,
            data={"updated": 0, "dryRun": True, "total": total, "unknownKeys": unknown},
        )

    provider = project_provider(work_cfg)
    score_model = score_model_for(work_cfg)
    manifest = RunManifest.start(
        command="rescore",
        locales=target_locales,
        model=score_model,
        config_hash=config_fingerprint({
            "score_model": score_model,
            "judge_model": getattr(work_cfg, "judge_model", None),
        }),
        source_locale=work_cfg.source_locale,
    )
    manifest.bump("work", total)
    provider.ensure_ready(score_model, report=_report)
    updated, low = rescore_items(
        provider, work_cfg, scores, glossary, work,
        report=_report, force_bt=True,
    )
    stop = getattr(provider, "stop", None)
    if callable(stop):
        stop(score_model)

    try:
        manifest.finish(
            updated=updated,
            processed=updated,
            total=total,
            low_score=len(low),
            score_model=score_model,
        )
        manifest.write(work_cfg.state_root())
        report_run_summary(manifest)
    except OSError:
        pass

    return OpResult(
        ok=True,
        exit_code=0,
        command="rescore",
        summary=f"re-scored {updated} key(s)",
        lines=(lines[-80:] if len(lines) > 80 else lines) + ([""] + low[:50] if low else []),
        data={"updated": updated, "unknownKeys": unknown},
    )


def op_rescore(
    cfg: ProjectConfig,
    req: RescoreRequest,
    *,
    report: Reporter | None = None,
) -> OpResult:
    enqueue = (
        not req.dry_run
        and should_enqueue(submit=req.submit, inline=req.inline, tq=tq_available())
    )
    with cloud_session(
        cfg, "rescore", locales=req.locales,
        namespaces=resolve_namespaces(req.namespace, req.namespaces),
        keys=list(req.keys) if req.keys else None,
        take_hold=not enqueue,
        skip=req.dry_run,
    ) as blocked:
        if blocked is not None:
            return blocked
        return _op_rescore_body(cfg, req, enqueue=enqueue, report=report)


def _op_rescore_body(cfg, req, *, enqueue: bool, report: Reporter | None) -> OpResult:
    if enqueue:
        overrides: dict[str, str] = {}
        locales = list(req.locales) if req.locales else list(cfg.active_targets())
        if locales:
            overrides["--locales"] = ",".join(locales)
        namespaces = resolve_namespaces(req.namespace, req.namespaces)
        if req.model:
            overrides["--model"] = req.model
        if req.stale_only:
            overrides["--stale-only"] = "true"
        if req.below_score is not None:
            overrides["--below-score"] = str(req.below_score)
        if req.keys:
            overrides["--keys"] = ",".join(req.keys)
        try:
            any_ok, messages, task_ids = enqueue_namespace_jobs(
                cfg, "rescore", overrides, namespaces,
            )
            summary = messages[0] if messages else ""
            return OpResult(
                ok=any_ok,
                exit_code=0 if any_ok else 1,
                command="rescore",
                summary=summary,
                lines=messages,
                data={"submitted": any_ok, "taskIds": task_ids},
            )
        except TaskqueueNotFound as exc:
            return OpResult(ok=False, exit_code=1, command="rescore", summary=str(exc))

    # Local run when not enqueued. Cloud hold is owned by cloud_session in op_rescore.
    return execute_rescore(
        cfg,
        locales=req.locales,
        namespaces=resolve_namespaces(req.namespace, req.namespaces),
        model=req.model,
        dry_run=req.dry_run,
        stale_only=req.stale_only,
        below_score=req.below_score,
        keys=list(req.keys) if req.keys else None,
        report=report,
    )
