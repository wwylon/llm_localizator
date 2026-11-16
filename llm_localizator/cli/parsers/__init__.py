"""The ``llm-localizator`` argument parser, one module per command group (``build_parser`` assembles them)."""

from __future__ import annotations

import argparse

from .checks import _add_quality, _add_validate, _add_ingest_visual
from .project import _add_web, _add_scan, _add_projects, _add_places, _add_status
from .process import _add_analytics, _add_watch, _add_metrics, _add_workflow, _add_suggest_source_review_bulk_clear
from .agent import _add_hard_keys, _add_adopt, _add_agent_backlog, _add_explain_scan, _add_scan_decide, _add_patch, _add_apply, _add_migrate_state, _add_guide, _add_init
from .pipeline import _add_translate_run_translate, _add_documents_review, _add_sync_run_sync, _add_improve_run_improve, _add_rescore_run_rescore, _add_bakeoff_run_bakeoff, _add_export_import
from .common import DEFAULT_MARKETING_PORT, DEFAULT_WEB_PORT, add_project_args

__all__ = ["build_parser", "add_project_args", "DEFAULT_WEB_PORT", "DEFAULT_MARKETING_PORT"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-localizator",
        description="Local-LLM localisation: translate, validate, and scan message catalogues.",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    _add_validate(sub)
    _add_ingest_visual(sub)
    _add_web(sub)
    _add_scan(sub)
    _add_status(sub)
    _add_projects(sub)
    _add_places(sub)
    _add_analytics(sub)
    _add_watch(sub)
    _add_metrics(sub)
    _add_workflow(sub)
    _add_suggest_source_review_bulk_clear(sub)
    _add_hard_keys(sub)
    _add_adopt(sub)
    _add_agent_backlog(sub)
    _add_explain_scan(sub)
    _add_scan_decide(sub)
    _add_patch(sub)
    _add_apply(sub)
    _add_migrate_state(sub)
    _add_guide(sub)
    _add_init(sub)
    _add_translate_run_translate(sub)
    _add_documents_review(sub)
    _add_sync_run_sync(sub)
    _add_improve_run_improve(sub)
    _add_rescore_run_rescore(sub)
    _add_bakeoff_run_bakeoff(sub)
    _add_export_import(sub)
    _add_quality(sub)

    return parser
