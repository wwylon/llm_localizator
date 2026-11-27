"""End-of-run helpers for :mod:`translate` (summary, glossary batch, manifest)."""

from __future__ import annotations

from ..projects.context import effective_glossary_for
from .run_manifest import RunManifest, config_fingerprint


def summary_line(result) -> str:
    summary = f"(100%) Done. Written {result.written}/{result.total}"
    if result.aborted:
        summary = f"(100%) Aborted after sustained rejects. Written {result.written}/{result.total}"
    for count, text in (
        (len(result.rejected), "rejected (bad output -- kept existing)"),
        (len(result.blocked), "blocked (needs_context)"),
        (len(result.escalated), "rescued by the secondary model"),
        (len(result.skipped), "skipped (provider errors)"),
        (len(result.icu_failed), "icu_failed (flagged; ICU message failed whole and by fragments)"),
        (len(result.flagged_low_score), "low-score (queued for improve)"),
        (len(result.held), "held as drafts (below the write floor or not better)"),
        (len(result.external_edit), "edited outside the run (kept; run adopt)"),
    ):
        if count:
            summary += f", {count} {text}"
    return summary + "."


def batch_glossary(cfg, notes, llm_items):
    """The glossary for one batch: union of the domains of its keys, shared glossaries merged."""
    domain_union: list[str] = []
    for item in llm_items:
        for d in cfg.glossary_domains_for(
            item.namespace, key_domain=notes.domain(item.namespace, item.key),
        ) or []:
            if d not in domain_union:
                domain_union.append(d)
    return effective_glossary_for(
        cfg.glossary_path,
        domains=domain_union or None,
        shared=list(getattr(cfg, "glossary_shared", []) or []),
        conflict=getattr(cfg, "glossary_conflict", "own"),
    )


def start_manifest(cfg, work, pin_model, resume_locales) -> RunManifest:
    """The run manifest for one translate job."""
    return RunManifest.start(
        command="translate",
        locales=sorted({item.locale for item in work} or set(resume_locales)),
        model=pin_model,
        prompt_family=cfg.prompt_family_for(
            work[0].locale if work else (resume_locales[0] if resume_locales else "")
        ) if (work or resume_locales) else None,
        config_hash=config_fingerprint({
            "domain": cfg.domain,
            "models": dict(getattr(cfg, "models", {}) or {}),
            "judge_model": getattr(cfg, "judge_model", None),
            "prompt_family": getattr(cfg, "prompt_family", None),
        }),
        source_locale=cfg.source_locale,
    )
