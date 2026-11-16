"""``llm-localizator documents`` / ``run-documents`` and ``review`` / ``run-review``."""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path

from ..catalog import catalog_for
from ..ops.documents import (
    documents_dir,
    documents_state_path,
    execute_documents,
    markdown_ids,
)
from ..ops.types import parse_csv_list
from ..pipeline.documents import draft_section_edits
from ..pipeline.review import run_review
from ..projects import resolve
from ..projects.taskqueue import TaskqueueNotFound, submit
from ..providers import project_provider
from ..catalog.io import read_json

__all__ = ["run_submit", "run_documents", "run_review_cmd"]


def run_submit(args: argparse.Namespace, job: str) -> int:
    cfg = resolve(args.project, args.config)
    if job == "documents" and getattr(args, "draft_edits", False):
        return run_documents(args)
    if job == "documents":
        from ..ops.documents import op_documents
        from ..ops.types import DocumentsRequest

        result = op_documents(cfg, DocumentsRequest(
            locales=list(getattr(args, "locales", None) or []) or None,
            model=getattr(args, "model", None),
            dry_run=bool(getattr(args, "dry_run", False)),
            submit=not bool(getattr(args, "dry_run", False)),
            doc=getattr(args, "doc", None),
            doc_dir=getattr(args, "doc_dir", None),
        ))
        if result.summary:
            print(result.summary)
        for line in result.lines:
            print(line)
        return result.exit_code
    if job == "review":
        from ..ops.review import op_review
        from ..ops.types import ReviewRequest

        result = op_review(cfg, ReviewRequest(
            locales=list(getattr(args, "locales", None) or []) or None,
            model=getattr(args, "model", None),
            dry_run=bool(getattr(args, "dry_run", False)),
            submit=not bool(getattr(args, "dry_run", False)),
            keys=parse_csv_list(getattr(args, "keys", None)),
            namespace=getattr(args, "namespace", None),
        ))
        if result.summary:
            print(result.summary)
        for line in result.lines:
            print(line)
        return result.exit_code
    overrides: dict[str, str] = {}
    if getattr(args, "locales", None):
        overrides["--locales"] = ",".join(args.locales)
    if getattr(args, "model", None):
        overrides["--model"] = args.model
    if getattr(args, "dry_run", False):
        overrides["--dry-run"] = "true"
    keys = parse_csv_list(getattr(args, "keys", None))
    if keys:
        overrides["--keys"] = ",".join(keys)
    try:
        return submit(cfg, job, overrides).exit_code
    except TaskqueueNotFound as exc:
        print(f"error: {exc}")
        return 1


def run_documents(args: argparse.Namespace) -> int:
    cfg = resolve(args.project, args.config)
    doc_dir = documents_dir(cfg, args.doc_dir)
    if not doc_dir.is_dir():
        print(f"error: no document directory at {doc_dir} "
              f"(set [documents] dir, or pass --doc-dir)")
        return 64

    source_dir = doc_dir / cfg.source_locale
    docs = [args.doc] if args.doc else markdown_ids(source_dir)
    if not docs:
        print(f"error: no .md documents under {source_dir}")
        return 64

    locales = list(args.locales or cfg.active_targets())
    model = args.model or cfg.documents_model

    if getattr(args, "draft_edits", False):
        return _print_edit_drafts(cfg, doc_dir, source_dir, docs, locales, model)

    result = execute_documents(
        cfg,
        locales=locales,
        docs=docs,
        doc_dir=doc_dir,
        model=model,
        dry_run=bool(args.dry_run),
        report=print,
    )
    return result.exit_code


def _print_edit_drafts(cfg, doc_dir, source_dir, docs, locales, model) -> int:
    """C-052: show minimal-edit drafts for changed sections. Nothing is written."""
    provider = project_provider(cfg)
    found = 0
    for locale in locales:
        state_path = documents_state_path(cfg, doc_dir, locale)
        state = read_json(state_path) if state_path.exists() else {}
        for doc in docs:
            source = source_dir / f"{doc}.md"
            if not source.exists():
                continue
            drafts = draft_section_edits(
                source, doc_dir / locale / f"{doc}.md", locale, provider,
                model=model or cfg.model_for(locale), state=state.get(doc, {}),
            )
            for d in drafts:
                found += 1
                print(f"--- {locale}/{doc} section {d['index']} ---")
                print("\n".join(difflib.unified_diff(
                    d["previous"].splitlines(), d["draft"].splitlines(), "current", "draft", lineterm="")))
    print(f"{found} draft(s); nothing written. Retranslate with `documents` to apply.")
    return 0


def run_review_cmd(args: argparse.Namespace) -> int:
    from ..reporting import report

    cfg = resolve(args.project, args.config)
    catalog = catalog_for(cfg)
    provider = project_provider(cfg)

    for locale in (args.locales or cfg.targets):
        report(f"--- reviewing {locale} ---")
        run_review(
            cfg, catalog, provider,
            locale=locale,
            namespaces=[args.namespace] if args.namespace else None,
            batch_size=getattr(args, "batch_size", 5) or 5,
            model=args.model,
            dry_run=args.dry_run,
            keys=parse_csv_list(getattr(args, "keys", None)),
            report=report,
        )
    return 0
