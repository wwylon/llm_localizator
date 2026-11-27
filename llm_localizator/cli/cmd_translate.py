"""``llm-localizator translate`` and ``run-translate``.

Two commands, deliberately (ADR-2). ``translate`` submits a job and exits;
``run-translate`` does the work and is what the queue invokes.
"""

from __future__ import annotations

import argparse

from ..catalog import FlagStore, catalog_for
from ..ops.types import parse_csv_list
from ..pipeline.translate import run_translation
from ..projects import resolve
from ..providers import project_provider
from ..reporting import report

__all__ = ["run_submit", "run_execute"]


def read_keys_file(path: str) -> list[str]:
    """Keys from a file: one per line or comma-separated, ``#`` comments ignored, ``-`` is stdin."""
    import sys
    from pathlib import Path

    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    keys: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keys.extend(piece.strip() for piece in line.split(",") if piece.strip())
    return keys


def keys_from_args(args: argparse.Namespace) -> list[str] | None:
    """``--keys`` and ``--keys-file`` merged (file keys last, duplicates dropped)."""
    keys = list(parse_csv_list(getattr(args, "keys", None)) or [])
    path = getattr(args, "keys_file", None)
    if path:
        keys.extend(read_keys_file(path))
    return list(dict.fromkeys(keys)) or None


def run_submit(args: argparse.Namespace, job: str = "translate") -> int:
    """Enqueue the job via ops (cloud gates stay single-sourced)."""
    cfg = resolve(args.project, args.config)
    collection = getattr(args, "collection", None)
    from ..ops.translate import op_translate
    from ..ops.types import TranslateRequest

    # *job* is always "translate" here (cli.main routes documents/review to
    # cmd_documents); the parameter stays for the shared run_submit signature.
    result = op_translate(cfg, TranslateRequest(
        locales=list(getattr(args, "locales", None) or []) or None,
        namespace=getattr(args, "namespace", None),
        namespaces=parse_csv_list(getattr(args, "namespace", None)),
        collection=collection if collection and collection != "messages" else None,
        model=getattr(args, "model", None),
        batch_size=int(getattr(args, "batch_size", None) or cfg.translate_batch_size or 10),
        force=bool(getattr(args, "force", False)),
        flagged=bool(getattr(args, "flagged", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        keys=keys_from_args(args),
        only_missing=bool(getattr(args, "only_missing", False)),
        sync=bool(getattr(args, "sync", False)),
        submit=not bool(getattr(args, "dry_run", False)),
        pre_translate=bool(getattr(args, "pre_translate", False)),
        tags=parse_csv_list(getattr(args, "tags", None)),
        sample=getattr(args, "sample", None),
        icu_only=bool(getattr(args, "icu_only", False)),
        plain_only=bool(getattr(args, "plain_only", False)),
    ))
    if result.summary:
        print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code


def _flagged_keys(cfg) -> dict[str, set[str]]:
    """Keys a developer flagged through the dev overlay, grouped by locale."""
    return FlagStore(cfg.flags_path).grouped()


def run_execute(args: argparse.Namespace) -> int:
    """Do the translation. Invoked by taskqueue, not usually by a human."""
    cfg = resolve(args.project, args.config)
    collection = getattr(args, "collection", None)
    if collection and collection != "messages":
        from ..ops.translate import op_translate
        from ..ops.types import TranslateRequest

        result = op_translate(cfg, TranslateRequest(
            locales=args.locales,
            collection=collection,
            model=args.model,
            dry_run=args.dry_run,
            keys=parse_csv_list(getattr(args, "keys", None)),
            submit=False,
            pre_translate=bool(getattr(args, "pre_translate", False)),
        ))
        if result.summary:
            print(result.summary)
        for line in result.lines:
            print(line)
        return result.exit_code
    catalog = catalog_for(cfg)
    provider = project_provider(cfg)

    if args.model:
        cfg.apply_model_override(args.model)

    only_keys = None
    manifest = getattr(args, "manifest", None)
    if manifest:
        from pathlib import Path

        from ..pipeline.manifest import only_keys_from

        try:
            only_keys = only_keys_from(Path(manifest))
        except (OSError, ValueError) as exc:
            print(f"error: cannot read manifest {manifest}: {exc}")
            return 1
        if not only_keys:
            print("(100%) The manifest lists no keys - nothing to do.")
            return 0
    elif args.flagged:
        only_keys = _flagged_keys(cfg)
        if not only_keys:
            print("(100%) No flagged keys - nothing to do.")
            return 0

    named = keys_from_args(args)
    tags = parse_csv_list(getattr(args, "tags", None))
    if tags:
        from ..projects.context import ContextNotes

        found = ContextNotes(cfg.context_dir).keys_with_tags(tags)
        named = [k for k in found if not named or k in named]
        if not named:
            print("(100%) No keys with those tags - nothing to do.")
            return 0
    if getattr(args, "sync", False):
        import dataclasses

        cfg = dataclasses.replace(cfg, budget_cloud_batch=False)
    result = run_translation(
        cfg, catalog, provider,
        locales=args.locales,
        namespaces=parse_csv_list(args.namespace),
        batch_size=args.batch_size or cfg.translate_batch_size or 10,
        force=args.force,
        dry_run=args.dry_run,
        only_keys=only_keys,
        named_keys=named,
        multi_sample=getattr(args, "multi_sample", None),
        ignore_min_keys=bool(getattr(args, "ignore_min_keys", False)),
        pre_translate=bool(getattr(args, "pre_translate", False)),
        trigger="pre-translate" if getattr(args, "pre_translate", False) else "translate",
        report=report,
        icu_only=bool(getattr(args, "icu_only", False)),
        plain_only=bool(getattr(args, "plain_only", False)),
        only_missing=bool(getattr(args, "only_missing", False)),
    )

    if result.rejected:
        print("Rejected keys (run with --force to retry):")
        for key in result.rejected:
            print(f"  {key}")
    return result.exit_code
