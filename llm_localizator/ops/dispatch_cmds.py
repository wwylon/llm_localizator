"""Per-command dispatch handlers and the ops registry (B3 split).

Imported by ``dispatch.py``; keep request-building here so ``dispatch_op``
stays permission / logging / confirm only.
"""

from __future__ import annotations

from collections.abc import Callable

from ..projects import ProjectConfig
from .acknowledge import op_acknowledge_flush
from .documents import op_documents
from .export_import import op_export, op_import
from .improve import op_improve
from .ingest_visual import op_ingest_visual
from .hard_keys import op_hard_keys
from .explain_scan import ExplainScanRequest, op_explain_scan
from .adopt import op_adopt
from .agent_backlog import op_agent_backlog
from .agent_hardcoded import op_agent_hardcoded
from .patch import op_patch
from .apply import op_apply
from .discover import op_discover
from .places import op_places
from .verify_run import op_verify_run
from .migrate import op_migrate
from .bakeoff import DEFAULT_LIMIT as DEFAULT_BAKEOFF_LIMIT, op_bakeoff
from .rescore import op_rescore
from .review import op_review
from .scan import op_scan
from .status import op_status
from .sync import op_sync
from .tm import op_concordance, op_tm_export, op_tm_import
from .glossary import op_glossary_export, op_glossary_import
from .source_ops import op_glossary_propose, op_impact, op_pseudo
from .translate import op_translate
from .terminology import op_term_report
from .release import op_release_diff, op_release_freeze
from .estimate_cost import op_estimate_cost
from .analytics import op_analytics
from .metrics import op_metrics
from .open_pr import op_open_pr
from .org import op_org
from .screenshot_link import op_screenshot_link
from .source_diff import op_source_diff
from .apply_near import op_apply_near
from .draft import op_draft
from .find_replace import op_find_replace
from .task import op_task
from .discuss import op_discuss
from .bulk_clear import op_bulk_clear
from .placeholder_rename import op_rename_placeholder
from .scan_decide import op_scan_decide
from .source_review import op_flag_source, op_source_review_queue
from .suggest import op_suggest
from .types import (
    request_from_mapping,
    AdoptRequest,
    AgentBacklogRequest,
    AgentHardcodedRequest,
    ApplyRequest,
    BakeoffRequest,
    PatchRequest,
    AnalyticsRequest,
    MetricsRequest,
    DocumentsRequest,
    ExportRequest,
    HardKeysRequest,
    ImportRequest,
    ImproveRequest,
    IngestVisualRequest,
    MigrateRequest,
    OpResult,
    RescoreRequest,
    ReviewRequest,
    ScanRequest,
    StatusRequest,
    VerifyRequest,
    ApplyNearRequest,
    DraftRequest,
    OpenPrRequest,
    ScreenshotLinkRequest,
    FindReplaceRequest,
    TaskRequest,
    DiscussRequest,
    BulkClearRequest,
    PlaceholderRenameRequest,
    ScanDecideRequest,
    FlagSourceRequest,
    SourceReviewQueueRequest,
    SuggestRequest,
    SyncRequest,
    TmExportRequest,
    TmImportRequest,
    GlossaryExportRequest,
    GlossaryImportRequest,
    PseudoRequest,
    ConcordanceRequest,
    TranslateRequest,
    EstimateCostRequest,
    ValidateRequest,
    parse_csv_list,
    resolve_namespaces,
)
from .validate import op_validate
from .dispatch_util import Reporter, _float_or, _int_or, _key_list, _ns_pair, _num_or, _op_catalog

from .command_descriptor import streamable_ops

STREAMABLE = streamable_ops()


# ---------------------------------------------------------------------------
# Per-command handler functions
# ---------------------------------------------------------------------------

def _cmd_acknowledge_flush(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_acknowledge_flush(cfg).to_dict()


def _cmd_validate(cfg: ProjectConfig, body: dict, report: Reporter | None, *, catalog=None) -> dict:
    namespace, namespaces = _ns_pair(body)
    semantic = bool(body.get("semantic"))
    check_length = bool(body.get("check_length"))
    detail = body.get("detail")
    if detail is None:
        detail = "full"
    findings_limit = body.get("findings_limit")
    if findings_limit is not None:
        try:
            findings_limit = int(findings_limit)
        except (TypeError, ValueError):
            findings_limit = None
    req = ValidateRequest(
        locales=body.get("locales"),
        namespace=namespace,
        namespaces=namespaces,
        strict=bool(body.get("strict")),
        check_expansion=bool(body.get("check_expansion")) or check_length,
        check_length=check_length,
        check_script=bool(body.get("check_script")) or semantic,
        check_digraphs=bool(body.get("check_digraphs")) or semantic,
        check_layout=bool(body.get("check_layout")),
        check_numbers=bool(body.get("check_numbers")),
        diff_only=bool(body.get("diff_only")),
        semantic=semantic,
        write_flags=bool(body.get("write_flags")),
        flag_checks=body.get("flag_checks", "V13"),
        diff_scope=body.get("diff_scope"),
        unused=bool(body.get("unused")),
        detail=str(detail),
        findings_limit=findings_limit,
    )
    return op_validate(cfg, req, catalog=catalog if catalog is not None else _op_catalog.get()).to_dict()


def _cmd_ingest_visual(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_ingest_visual(cfg, IngestVisualRequest(
        path=body.get("path"),
        dry_run=bool(body.get("dry_run")),
    )).to_dict()


def _cmd_status(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_status(
        cfg,
        StatusRequest(
            missing=bool(body.get("missing")),
            collection=body.get("collection") or None,
            by_screen=bool(body.get("by_screen")),
        ),
        catalog=_op_catalog.get(),
    ).to_dict()



def _cmd_concordance(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    source = body.get("source", True)
    target = body.get("target", True)
    if body.get("no_source"):
        source = False
    if body.get("no_target"):
        target = False
    return op_concordance(cfg, ConcordanceRequest(
        locale=str(body.get("locale") or ""),
        query=str(body.get("query") or ""),
        source=bool(source),
        target=bool(target),
        limit=_int_or(body, "limit", 20) or 20,
        namespace=body.get("namespace") or None,
        key=body.get("key") or None,
        mode=str(body.get("mode") or "substring"),
        min_similarity=_float_or(body.get("min_similarity"), 0.55),
    )).to_dict()


def _cmd_tm_export(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_tm_export(cfg, TmExportRequest(
        locale=str(body.get("locale") or ""),
        path=body.get("path") or body.get("out") or None,
    )).to_dict()


def _cmd_tm_import(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_tm_import(cfg, TmImportRequest(
        locale=str(body.get("locale") or ""),
        path=body.get("path") or body.get("file") or None,
        tmx=body.get("tmx") or None,
        conflict=str(body.get("conflict") or "skip"),
        dry_run=bool(body.get("dry_run")),
    )).to_dict()


def _cmd_glossary_export(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_glossary_export(cfg, GlossaryExportRequest(
        format=str(body.get("format") or "csv"),
        file=body.get("file") or body.get("out") or None,
    )).to_dict()


def _cmd_glossary_import(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_glossary_import(cfg, GlossaryImportRequest(
        format=str(body.get("format") or ""),
        file=body.get("file") or None,
        text=body.get("text") or body.get("csv") or body.get("tbx") or None,
        conflict=str(body.get("conflict") or "skip"),
        dry_run=bool(body.get("dry_run")),
    )).to_dict()


def _cmd_glossary_propose(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_glossary_propose(
        cfg,
        locale=body.get("locale"),
        min_occurrences=_int_or(body, "min_occurrences", 5) or 5,
        out=body.get("out"),
    ).to_dict()


def _cmd_impact(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_impact(cfg).to_dict()


def _cmd_pseudo(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    factor = body.get("length_factor", 1.4)
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        factor = 1.4
    return op_pseudo(cfg, PseudoRequest(
        locale=str(body.get("locale") or "en-XA"),
        length_factor=factor,
        style=str(body.get("style") or ""),
    )).to_dict()


def _cmd_hardcoded_hunt(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    from .hardcoded_hunt import op_hardcoded_hunt

    return op_hardcoded_hunt(
        cfg,
        skip_crawl=bool(body.get("skip_crawl")),
        skip_static=bool(body.get("skip_static")),
        no_serve=body.get("no_serve", True) is not False,
    ).to_dict()


def _cmd_term_report(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_term_report(cfg, locales=_key_list(body.get("locales")) or None).to_dict()


def _cmd_release_freeze(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    try:
        return op_release_freeze(
            cfg,
            name=str(body.get("name") or ""),
            namespaces=parse_csv_list(body.get("namespaces") or body.get("namespace")),
            keys=parse_csv_list(body.get("keys")),
        ).to_dict()
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "exit_code": 1, "command": "release-freeze"}


def _cmd_release_diff(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    try:
        return op_release_diff(cfg, name=str(body.get("name") or "")).to_dict()
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "exit_code": 1, "command": "release-diff"}


def _cmd_analytics(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_analytics(cfg, AnalyticsRequest(
        since=body.get("since"),
        run_command=body.get("run_command"),
        locale=body.get("locale"),
        locales=body.get("locales"),
        model=body.get("model"),
        last=body.get("last"),
        fmt=body.get("format", body.get("fmt", "text")),
    ), report=report).to_dict()


def _cmd_suggest(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    locale = body.get("locale") or (list(body.get("locales") or [""])[0])
    return op_suggest(cfg, SuggestRequest(
        locale=locale, namespace=body.get("namespace") or "", key=body.get("key") or "",
        explain=bool(body.get("explain")),
        alternatives=bool(body.get("alternatives")),
        ambiguity=bool(body.get("ambiguity")),
    )).to_dict()


def _cmd_draft(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    keys = body.get("keys")
    if isinstance(keys, str):
        keys = [p.strip() for p in keys.split(",") if p.strip()]
    return op_draft(cfg, DraftRequest(
        action=body.get("action") or "list",
        locale=body.get("locale") or (list(body.get("locales") or [""])[0]),
        namespace=body.get("namespace") or "", key=body.get("key") or "",
        keys=keys or None, by=body.get("by") or body.get("actor") or "",
        mode=body.get("mode") or "", confirm=bool(body.get("confirm")),
    )).to_dict()


def _cmd_open_pr(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_open_pr(cfg, OpenPrRequest(
        # The form sends argparse dests (``pr_branch``, ``yes``); API callers may still send branch/confirm.
        action=body.get("action") or "plan", branch=body.get("pr_branch") or body.get("branch") or "",
        confirm=bool(body.get("confirm") or body.get("yes")),
    )).to_dict()


def _cmd_screenshot_link(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_screenshot_link(cfg, ScreenshotLinkRequest(
        action=body.get("action") or "list", file=body.get("file") or "",
        namespace=body.get("namespace") or "", key=body.get("key") or "",
        region=body.get("region"), note=body.get("note") or "",
        link=body.get("link") or "", by=body.get("by") or "",
    )).to_dict()


def _cmd_source_diff(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    locale = body.get("locale") or (list(body.get("locales") or [""])[0])
    return op_source_diff(cfg, locale, body.get("namespace") or "", body.get("key") or "").to_dict()


def _cmd_task(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    keys, assign = body.get("keys"), body.get("assign")
    if isinstance(keys, str):
        keys = [p.strip() for p in keys.split(",") if p.strip()]
    if isinstance(assign, str):
        assign = [p.strip() for p in assign.split(",") if p.strip()]
    elif isinstance(assign, dict):
        assign = [f"{k}={v}" for k, v in assign.items()]
    return op_task(cfg, TaskRequest(
        action=body.get("action") or "list", id=body.get("id") or "", name=body.get("name") or "",
        namespace=body.get("namespace") or None, keys=keys or None, assign=assign or None,
        due=body.get("due") or "", unverified=bool(body.get("unverified")),
        assignee=body.get("assignee") or "", by=body.get("by") or body.get("actor") or "",
    )).to_dict()


def _cmd_discuss(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_discuss(cfg, DiscussRequest(
        action=body.get("action") or "list", namespace=body.get("namespace") or "",
        key=body.get("key") or "", text=body.get("text") or "",
        mention=body.get("mention") or "", open_only=bool(body.get("open_only")),
        by=body.get("by") or body.get("actor") or "",
    )).to_dict()


def _cmd_flag_source(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_flag_source(cfg, FlagSourceRequest(
        namespace=body.get("namespace") or "", key=body.get("key") or "",
        note=body.get("note") or "",
    )).to_dict()


def _cmd_source_review_queue(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_source_review_queue(cfg, SourceReviewQueueRequest()).to_dict()


def _cmd_apply_near(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    keys = body.get("keys")
    if isinstance(keys, str):
        keys = [p.strip() for p in keys.split(",") if p.strip()]
    sim = body.get("min_similarity")
    return op_apply_near(cfg, ApplyNearRequest(
        locale=body.get("locale") or (list(body.get("locales") or [""])[0]),
        namespace=body.get("namespace") or "", key=body.get("key") or "",
        min_similarity=float(sim) if sim not in (None, "") else 0.85,
        keys=keys or None, dry_run=bool(body.get("dry_run")), confirm=bool(body.get("confirm")),
    )).to_dict()


def _cmd_find_replace(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    keys = body.get("keys")
    if isinstance(keys, str):
        keys = [p.strip() for p in keys.split(",") if p.strip()]
    return op_find_replace(cfg, FindReplaceRequest(
        locale=body.get("locale") or (list(body.get("locales") or [""])[0]),
        find=body.get("find") or "", replace=body.get("replace") or "",
        namespace=body.get("namespace") or None,
        case_sensitive=bool(body.get("case_sensitive")),
        keys=keys or None, dry_run=bool(body.get("dry_run")), confirm=bool(body.get("confirm")),
    )).to_dict()


def _cmd_bulk_clear(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    older = body.get("purge_machine_older_than")
    locales = body.get("locales")
    if isinstance(locales, str):
        locales = [p.strip() for p in locales.split(",") if p.strip()]
    return op_bulk_clear(cfg, BulkClearRequest(
        locale=body.get("locale"), locales=locales or None,
        namespace=body.get("namespace"),
        stale_to_source=bool(body.get("stale_to_source")),
        purge_machine_older_than=int(older) if older not in (None, "") else None,
        invalid=bool(body.get("invalid")), latin_leftover=bool(body.get("latin_leftover")),
        dry_run=bool(body.get("dry_run")), confirm=bool(body.get("confirm")),
    )).to_dict()


def _cmd_rename_placeholder(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_rename_placeholder(cfg, PlaceholderRenameRequest(
        old=str(body.get("old") or ""), new=str(body.get("new") or ""),
        namespace=body.get("namespace"), keys=_key_list(body.get("keys")),
        dry_run=bool(body.get("dry_run")), confirm=bool(body.get("confirm")),
    )).to_dict()


def _cmd_scan_decide(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_scan_decide(cfg, request_from_mapping(ScanDecideRequest, body)).to_dict()


def _cmd_org(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_org(cfg).to_dict()


def _cmd_metrics(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_metrics(
        cfg,
        MetricsRequest(
            since=body.get("since"),
            locale=body.get("locale"),
            locales=body.get("locales"),
            by=body.get("by") or None,
            fmt=body.get("format", body.get("fmt", "text")),
            why_low=bool(body.get("why_low")),
            threshold=_num_or(body, "threshold", None),
        ),
        catalog=_op_catalog.get(),
    ).to_dict()


def _cmd_sync(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    req = SyncRequest(
        locales=body.get("locales"),
        dry_run=bool(body.get("dry_run")),
        no_translate=bool(body.get("no_translate")),
        submit_translate=bool(body.get("submit_translate")),
        strict_branch=bool(body.get("strict_branch")),
        diff=bool(body.get("diff")),
        exit_nonzero=bool(body.get("exit_nonzero")),
    )
    return op_sync(cfg, req).to_dict()


def _cmd_translate(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    namespace, namespaces = _ns_pair(body)
    req = TranslateRequest(
        locales=body.get("locales"),
        collection=body.get("collection") or None,
        namespace=namespace,
        namespaces=namespaces,
        model=body.get("model"),
        batch_size=_int_or(body, "batch_size", cfg.translate_batch_size or 10),
        force=bool(body.get("force")),
        flagged=bool(body.get("flagged")),
        dry_run=bool(body.get("dry_run")),
        multi_sample=body.get("multi_sample"),
        submit=bool(body.get("submit")),
        keys=_key_list(body.get("keys")),
        pre_translate=bool(body.get("pre_translate")),
        tags=_key_list(body.get("tags")),
        inline=bool(body.get("inline")),
        icu_only=bool(body.get("icu_only") or body.get("icuOnly")),
        sample=body.get("sample") or None,
        plain_only=bool(body.get("plain_only") or body.get("plainOnly")),
    )
    # Align with apply/bulk-clear for *inline* runs. Queue-preferring paths
    # (tq on PATH, no inline) do not need confirm — the worker is the spend gate.
    from .queue_policy import should_enqueue
    from ..projects.taskqueue import tq_available

    if (
        not req.dry_run
        and not should_enqueue(
            submit=req.submit, inline=req.inline, tq=tq_available(),
        )
        and not body.get("confirm")
    ):
        return {"ok": False, "error": "set confirm=true to run translate"}
    return op_translate(cfg, req, report=report).to_dict()


def _cmd_estimate_cost(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    namespaces = resolve_namespaces(body.get("namespace"), body.get("namespaces"))
    return op_estimate_cost(cfg, EstimateCostRequest(
        locales=body.get("locales"),
        namespace=body.get("namespace"),
        namespaces=namespaces,
        keys=_key_list(body.get("keys")),
        batch_size=_int_or(body, "batch_size", cfg.translate_batch_size or 10) or 10,
        collection=body.get("collection") or None,
        purpose=str(body.get("purpose") or "translate"),
    )).to_dict()


def _cmd_improve(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    namespace, namespaces = _ns_pair(body)
    req = ImproveRequest(
        locales=body.get("locales"),
        namespace=namespace,
        namespaces=namespaces,
        model=body.get("model"),
        limit=body.get("limit"),
        dry_run=bool(body.get("dry_run")),
        submit=bool(body.get("submit")),
        include_rejected=bool(body.get("include_rejected")),
        keys=_key_list(body.get("keys")),
        tags=_key_list(body.get("tags")),
        inline=bool(body.get("inline")),
    )
    from .queue_policy import should_enqueue
    from ..projects.taskqueue import tq_available

    if (
        not req.dry_run
        and not should_enqueue(
            submit=req.submit, inline=req.inline, tq=tq_available(),
        )
        and not body.get("confirm")
    ):
        return {"ok": False, "error": "set confirm=true to run improve"}
    return op_improve(cfg, req, report=report).to_dict()



def _spend_gate(command: str, body: dict, *, queueable: bool = True) -> dict | None:
    """Inline LLM runs need ``confirm`` (M0, audit ops #14); dry runs and queued runs do not (the worker is the gate).

    The web Ops drawer sends ``confirm`` for every inline run; API and agent callers must say so explicitly.
    """
    if body.get("dry_run") or body.get("confirm"):
        return None
    if queueable:
        from .queue_policy import should_enqueue
        from ..projects.taskqueue import tq_available

        if should_enqueue(submit=bool(body.get("submit")), inline=bool(body.get("inline")), tq=tq_available()):
            return None
    return {"ok": False, "exit_code": 64, "error": f"set confirm=true to run {command}",
            "summary": f"set confirm=true to run {command}"}

def _cmd_review(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    gate = _spend_gate("review", body)
    if gate:
        return gate
    namespace, namespaces = _ns_pair(body)
    req = ReviewRequest(
        locales=body.get("locales"),
        namespace=namespace,
        namespaces=namespaces,
        model=body.get("model"),
        batch_size=_int_or(body, "batch_size", 5),
        dry_run=bool(body.get("dry_run")),
        submit=bool(body.get("submit")),
        keys=_key_list(body.get("keys")),
        inline=bool(body.get("inline")),
    )
    return op_review(cfg, req, report=report).to_dict()


def _cmd_hard_keys(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    namespace, namespaces = _ns_pair(body)
    return op_hard_keys(cfg, HardKeysRequest(
        locales=body.get("locales"),
        namespace=namespace,
        namespaces=namespaces,
        threshold=_num_or(body, "threshold", 0.7),
        min_locales=_int_or(body, "min_locales", 4),
        dry_run=bool(body.get("dry_run")),
    ), report=report).to_dict()


def _cmd_engine(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    from .engines import op_engine

    vram = body.get("vram")
    return op_engine(
        cfg, str(body.get("action") or "list"), (str(body.get("engine_id") or "") or None),
        accept_unbenchmarked=bool(body.get("accept_unbenchmarked")),
        vram=_float_or(vram, None) if vram not in (None, "") else None,
        gpu_busy=bool(body.get("gpu_busy")),
        url=(str(body.get("url") or "") or None), write=bool(body.get("write")),
        accept_unverified=bool(body.get("accept_unverified")),
    ).to_dict()


def _cmd_approach(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    from .approaches import op_approach

    set_to = str(body.get("set_to") or body.get("set") or "").strip() or None
    return op_approach(cfg, set_to=set_to).to_dict()


def _cmd_queue_engine(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    from .queue import op_queue_engine

    return op_queue_engine(cfg, str(body.get("engine_id") or ""), dry_run=bool(body.get("dry_run"))).to_dict()


def _cmd_explain_scan(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    target = str(body.get("target") or "").strip()
    if not target and body.get("file"):
        line = str(body.get("line") or "").strip()
        target = f"{body['file']}:{line}" if line else str(body["file"])
    return op_explain_scan(cfg, ExplainScanRequest(target=target, adapter=body.get("adapter") or None)).to_dict()


def _cmd_adopt(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    namespace, namespaces = _ns_pair(body)
    return op_adopt(cfg, AdoptRequest(
        locales=body.get("locales"),
        namespace=namespace,
        namespaces=namespaces,
        dry_run=bool(body.get("dry_run")),
        limit=body.get("limit"),
        model=body.get("model") or "cursor-agent",
        provider=body.get("provider") or "agent",
        verified_by=body.get("verified_by") or body.get("verifiedBy") or "cursor-agent",
    )).to_dict()


def _cmd_agent_backlog(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    namespace, namespaces = _ns_pair(body)
    reasons = body.get("reasons")
    if isinstance(reasons, str):
        reasons = [r.strip() for r in reasons.split(",") if r.strip()]
    return op_agent_backlog(cfg, AgentBacklogRequest(
        locales=body.get("locales"),
        namespace=namespace,
        namespaces=namespaces,
        reasons=reasons,
        limit=body.get("limit"),
        fmt=body.get("format", body.get("fmt", "prompt")),
        include_existing=bool(
            body.get("include_existing") or body.get("includeExisting")
        ),
        split=body.get("split") or None,
        out_dir=body.get("out_dir") or None,
        budget_tokens=_int_or(body, "budget_tokens", 15000) or 15000,
    )).to_dict()


def _cmd_agent_hardcoded(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    if body.get("llm"):
        gate = _spend_gate("agent-hardcoded --llm", body, queueable=False)
        if gate:
            return gate
    limit = body.get("limit")
    if limit in ("", None):
        limit_n = None
    else:
        try:
            limit_n = int(limit)
        except (TypeError, ValueError):
            limit_n = None
    if body.get("status"):
        from .agent_hardcoded import scan_cache_status

        data = scan_cache_status(cfg)
        return {"ok": True, "exit_code": 0, "command": "agent-hardcoded", "data": data,
                "summary": "scan cache and QA marker readiness", "lines": []}
    return op_agent_hardcoded(cfg, AgentHardcodedRequest(
        adapter=body.get("adapter") or None,
        limit=limit_n,
        fmt=body.get("format", body.get("fmt", "prompt")),
        llm=bool(body.get("llm")),
        dry_run=bool(body.get("dry_run")),
        submit=bool(body.get("submit")),
        catalogue_audit=body.get("catalogue_audit", True) is not False,
        refresh=bool(body.get("refresh")),
        show_ignored=bool(body.get("show_ignored")),
        show_low=bool(body.get("show_low")),
        split=body.get("split") or None,
        budget_tokens=_int_or(body, "budget_tokens", 15000) or 15000,
        max_hits=_int_or(body, "max_hits", 150) or 150,
        out_dir=body.get("out_dir") or None,
    )).to_dict()


def _cmd_patch(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    limit = body.get("limit")
    try:
        limit_n = int(limit) if limit not in (None, "") else None
    except (TypeError, ValueError):
        limit_n = None
    return op_patch(cfg, PatchRequest(
        adapter=body.get("adapter") or None,
        limit=limit_n,
        out_dir=body.get("out_dir") or body.get("outDir") or None,
        fmt=body.get("format", body.get("fmt", "json")),
    )).to_dict()


def _cmd_apply(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    limit = body.get("limit")
    try:
        limit_n = int(limit) if limit not in (None, "") else None
    except (TypeError, ValueError):
        limit_n = None
    return op_apply(cfg, ApplyRequest(
        adapter=body.get("adapter") or None,
        limit=limit_n,
        dry_run=bool(body.get("dry_run")),
        confirm=bool(body.get("confirm")),
        enqueue_translate=body.get("enqueue_translate", True) is not False,
    )).to_dict()


def _cmd_discover(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_discover(cfg).to_dict()


def _cmd_verify(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    path = str(body.get("path") or "").strip()
    if not path:
        return OpResult(
            ok=False, exit_code=64, command="verify",
            summary="path is required", lines=["verify needs an explicit project path"],
        ).to_dict()
    return op_verify_run(VerifyRequest(
        path=path,
        profile=body.get("profile") or "quick",
        locales=body.get("locales") or None,
        out=body.get("out") or None,
        resume=body.get("resume") or None,
        only=body.get("only"),
        skip=body.get("skip"),
    )).to_dict()


def _cmd_projects(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    from ..projects import ConfigError
    from ..projects.registry import list_projects, prune_projects, rename_project, unregister_project

    action = str(body.get("action") or "list")
    names = [str(n) for n in (body.get("names") or [])]
    try:
        if action == "remove" and len(names) == 1:
            unregister_project(names[0])
            summary = f"unregistered {names[0]} (project files untouched)"
        elif action == "rename" and len(names) == 2:
            rename_project(*names)
            summary = f"renamed {names[0]} -> {names[1]}"
        elif action == "prune":
            gone = prune_projects()
            summary = f"pruned {len(gone)} missing project(s)"
        elif action == "list":
            rows = list_projects()
            return OpResult(ok=True, exit_code=0, command="projects",
                            summary=f"{len(rows)} project(s)", data={"projects": rows}).to_dict()
        else:
            raise ConfigError("usage: projects list | remove NAME | rename OLD NEW | prune")
    except ConfigError as exc:
        return OpResult(ok=False, exit_code=1, command="projects", summary=str(exc)).to_dict()
    return OpResult(ok=True, exit_code=0, command="projects", summary=summary).to_dict()


def _cmd_places(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_places(
        cfg,
        str(body.get("action") or "list"),
        str(body.get("place") or ""),
        str(body.get("policy") or ""),
        catalog=_op_catalog.get(),
    ).to_dict()


def _cmd_export(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    namespace, namespaces = _ns_pair(body)
    return op_export(cfg, ExportRequest(
        locales=body.get("locales"),
        collection=body.get("collection") or None,
        namespace=namespace,
        namespaces=namespaces,
        fmt=body.get("format", body.get("fmt", "csv")),
        only=body.get("only") or "all",
        layout=body.get("layout") or "single",
        screenshots=bool(body.get("screenshots")),
        file_count=1 if body.get("file_count") is None else body.get("file_count"),
        approved_only=bool(body.get("approved_only")),
        xliff_version=str(body.get("xliff_version") or "1.2"),
        bom=bool(body.get("bom")),
    )).to_dict()


def _cmd_import(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    text = body.get("csv") or body.get("xliff") or body.get("data") or body.get("text") or ""
    files = body.get("files")
    return op_import(cfg, ImportRequest(
        text=text,
        files=files if isinstance(files, list) else None,
        locales=body.get("locales"),
        fmt=body.get("format", body.get("fmt", "csv")),
        dry_run=bool(body.get("dry_run")),
        model=str(body.get("model") or body.get("localized_by") or "import"),
    )).to_dict()


def _cmd_bakeoff(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    gate = _spend_gate("bakeoff", body)
    if gate:
        return gate
    return op_bakeoff(cfg, BakeoffRequest(
        locales=_key_list(body.get("locales")),
        models=_key_list(body.get("models")),
        limit=_int_or(body, "limit", DEFAULT_BAKEOFF_LIMIT) or DEFAULT_BAKEOFF_LIMIT,
        corpus=body.get("corpus") or None,
        out=body.get("out") or None,
        family=body.get("family") or None,
        matrix=bool(body.get("matrix")),
        force_cells=bool(body.get("force_cells")),
        dry_run=bool(body.get("dry_run")),
        submit=bool(body.get("submit")),
        inline=bool(body.get("inline")),
        propose_config=bool(body.get("propose_config")),
    ), report=report).to_dict()


def _cmd_rescore(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    gate = _spend_gate("rescore", body)
    if gate:
        return gate
    namespace, namespaces = _ns_pair(body)
    return op_rescore(cfg, RescoreRequest(
        locales=body.get("locales"),
        namespace=namespace,
        namespaces=namespaces,
        model=body.get("model"),
        dry_run=bool(body.get("dry_run")),
        submit=bool(body.get("submit")),
        stale_only=bool(body.get("stale_only")),
        below_score=body.get("below_score"),
        keys=_key_list(body.get("keys")),
        inline=bool(body.get("inline")),
    ), report=report).to_dict()


def _cmd_scan(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_scan(cfg, ScanRequest(
        adapter=body.get("adapter"),
        out_dir=body.get("out_dir"),
        no_write=bool(body.get("no_write")),
        strict=bool(body.get("strict")),
        lint_directives=bool(body.get("lint_directives")),
    )).to_dict()


def _cmd_migrate_state(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    return op_migrate(cfg, MigrateRequest(
        locales=body.get("locales"),
        dry_run=bool(body.get("dry_run")),
        stamp_provider=bool(body.get("stamp_provider") or body.get("stampProvider")),
    )).to_dict()


def _cmd_documents(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    gate = _spend_gate("documents", body)
    if gate:
        return gate
    return op_documents(cfg, DocumentsRequest(
        locales=body.get("locales"),
        doc=body.get("doc"),
        doc_dir=body.get("doc_dir"),
        model=body.get("model"),
        dry_run=bool(body.get("dry_run")),
        submit=bool(body.get("submit")),
        inline=bool(body.get("inline")),
    ), report=report).to_dict()


def _cmd_explain_skip(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    from .explain_skip import ExplainSkipRequest, op_explain_skip

    return op_explain_skip(cfg, ExplainSkipRequest(
        namespace=body.get("namespace") or None,
        key=body.get("key") or None,
        locale=body.get("locale") or None,
        limit=_int_or(body, "limit", 50) or 50,
    )).to_dict()


def _cmd_push_strings(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    from .push_strings import PushStringsRequest, op_push_strings

    strings = body.get("strings")
    if not isinstance(strings, dict):
        strings = {}
    return op_push_strings(cfg, PushStringsRequest(
        namespace=str(body.get("namespace") or ""),
        strings={str(k): str(v) if v is not None else "" for k, v in strings.items()},
        dry_run=bool(body.get("dry_run")),
    )).to_dict()


def _cmd_workflow(cfg: ProjectConfig, body: dict, report: Reporter | None) -> dict:
    from .workflow import WorkflowRequest, op_workflow_run

    return op_workflow_run(cfg, WorkflowRequest(
        name=str(body.get("name") or body.get("workflow") or "default"),
        locales=body.get("locales"),
        namespace=body.get("namespace"),
        namespaces=body.get("namespaces"),
        dry_run=bool(body.get("dry_run")),
        route_only=bool(body.get("route_only") or body.get("routeOnly")),
        submit=bool(body.get("submit")),
        inline=bool(body.get("inline")),
        resume=str(body["resume"]) if body.get("resume") else None,
    )).to_dict()


# Registry maps normalized command name (underscores) → handler function.
# Keys use underscores; dispatch_op normalises hyphens before lookup.
_REGISTRY: dict[str, Callable[[ProjectConfig, dict, Reporter | None], dict]] = {
    "acknowledge_flush": _cmd_acknowledge_flush,
    "validate": _cmd_validate,
    "ingest_visual": _cmd_ingest_visual,
    "status": _cmd_status,
    "concordance": _cmd_concordance,
    "tm_export": _cmd_tm_export,
    "tm_import": _cmd_tm_import,
    "glossary_export": _cmd_glossary_export,
    "glossary_import": _cmd_glossary_import,
    "glossary_propose": _cmd_glossary_propose,
    "impact": _cmd_impact,
    "pseudo": _cmd_pseudo,
    "hardcoded_hunt": _cmd_hardcoded_hunt,
    "term_report": _cmd_term_report,
    "release_freeze": _cmd_release_freeze,
    "release_diff": _cmd_release_diff,
    "analytics": _cmd_analytics,
    "metrics": _cmd_metrics,
    "org": _cmd_org,
    "suggest": _cmd_suggest,
    "draft": _cmd_draft,
    "source_diff": _cmd_source_diff,
    "open_pr": _cmd_open_pr,
    "screenshot_link": _cmd_screenshot_link,
    "task": _cmd_task,
    "discuss": _cmd_discuss,
    "flag_source": _cmd_flag_source,
    "source_review_queue": _cmd_source_review_queue,
    "bulk_clear": _cmd_bulk_clear,
    "apply_near": _cmd_apply_near,
    "find_replace": _cmd_find_replace,
    "rename_placeholder": _cmd_rename_placeholder,
    "scan_decide": _cmd_scan_decide,
    "sync": _cmd_sync,
    "translate": _cmd_translate,
    "estimate_cost": _cmd_estimate_cost,
    "improve": _cmd_improve,
    "review": _cmd_review,
    "hard_keys": _cmd_hard_keys,
    "explain_scan": _cmd_explain_scan,
    "engine": _cmd_engine,
    "queue_engine": _cmd_queue_engine,
    "approach": _cmd_approach,
    "adopt": _cmd_adopt,
    "agent_backlog": _cmd_agent_backlog,
    "agent_hardcoded": _cmd_agent_hardcoded,
    "patch": _cmd_patch,
    "apply": _cmd_apply,
    "discover": _cmd_discover,
    "verify": _cmd_verify,
    "projects": _cmd_projects,
    "places": _cmd_places,
    "export": _cmd_export,
    "import": _cmd_import,
    "rescore": _cmd_rescore,
    "bakeoff": _cmd_bakeoff,
    "scan": _cmd_scan,
    "migrate_state": _cmd_migrate_state,
    "documents": _cmd_documents,
    "push_strings": _cmd_push_strings,
    "workflow": _cmd_workflow,
    "explain_skip": _cmd_explain_skip,
}
