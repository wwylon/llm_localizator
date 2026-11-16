"""Argparse builders: translate, documents, review, sync, improve, rescore, bakeoff, export, import."""

from __future__ import annotations

import argparse
from pathlib import Path

from .common import _csv, add_project_args, _positive_int


def _add_translate_run_translate(sub: argparse._SubParsersAction) -> None:
    """Subcommands: translate / run-translate."""
    for name, helptext in [
        ("translate", "Submit a translation job to taskqueue and exit"),
        ("run-translate", "Execute a translation job (invoked by taskqueue)"),
    ]:
        t = sub.add_parser(name, help=helptext)
        add_project_args(t)
        t.add_argument("--collection", default=None,
                       help="Text collection (default: messages). File collections use the documents pipeline. "
                            "A remote collection translates each unit from its source_locale.")
        t.add_argument("--locales", type=_csv, default=None, metavar="LIST",
                       help="Comma-separated target locales (default: all configured)")
        t.add_argument(
            "--namespace", action="append", default=None,
            help="Restrict to these namespaces (repeatable, or comma-separated)",
        )
        t.add_argument("--engine", default=None,
                         help="Use this engine for this run only (llm-localizator engine list); the config is not changed")
        t.add_argument("--model", default=None, help="Override the model for every locale")
        t.add_argument("--batch-size", type=_positive_int, default=None,
                       help="Keys per request (default: [translate] batch_size, else 10)")
        t.add_argument(
            "--keys", action="append", default=None, metavar="KEY",
            help=(
                "Explicit keys (namespace.key), repeatable or comma-separated. "
                "Required for a cloud run when [budget] mode = \"on_request\"."
            ),
        )
        t.add_argument("--tag", dest="tags", action="append", default=None, metavar="TAG",
                       help="Only keys carrying this context tag (repeatable or comma-separated)")
        t.add_argument("--force", action="store_true", help="Retranslate up-to-date keys")
        t.add_argument("--sample", default=None, metavar="layout[:N]",
                       help="Translate only a layout-check sample (short chrome, longest, spread)")
        t.add_argument("--flagged", action="store_true",
                       help="Only keys flagged through the dev overlay")
        t.add_argument("--manifest", default=None, metavar="PATH",
                       help="Only the keys listed in a work manifest (from `sync --diff`)")
        t.add_argument("--dry-run", action="store_true",
                       help="Report the work list without calling the model or writing")
        t.add_argument("--pre-translate", action="store_true",
                       help="Write the translation without a score or a low-score flag")
        t.add_argument(
            "--ignore-min-keys", action="store_true",
            help=(
                "Bypass [translate] min_keys (operator runs). "
                "Automated sync→translate chains omit this so the floor still applies."
            ),
        )
        t.add_argument(
            "--multi-sample", type=int, default=None, metavar="N",
            help="Best-of-N candidates with BT scoring (overrides [quality] multi_sample)",
        )
        lane = t.add_mutually_exclusive_group()
        lane.add_argument("--icu-only", action="store_true",
                          help="Residual lane: only keys whose ICU message needs decomposition (plural/select)")
        lane.add_argument("--plain-only", action="store_true",
                          help="Residual lane: only keys without a plural/select ICU structure")


def _add_documents_review(sub: argparse._SubParsersAction) -> None:
    """Subcommands: documents / review."""
    for name, helptext in [
        ("documents", "Submit a Markdown document translation job to taskqueue"),
        ("run-documents", "Execute a document translation job (invoked by taskqueue)"),
    ]:
        d = sub.add_parser(name, help=helptext)
        add_project_args(d)
        d.add_argument("--locales", type=_csv, default=None)
        d.add_argument("--doc", default=None, help="Single document stem, e.g. 'terms'")
        d.add_argument("--doc-dir", default=None,
                       help="Document root (default: <project>/content/legal)")
        d.add_argument("--engine", default=None,
                         help="Use this engine for this run only (llm-localizator engine list); the config is not changed")
        d.add_argument("--model", default=None)
        d.add_argument("--dry-run", action="store_true")
        d.add_argument("--draft-edits", action="store_true",
                       help="Print minimal-edit drafts for changed sections; writes nothing (C-052)")

    for name, helptext in [
        ("review", "Submit an LLM review pass to taskqueue"),
        ("run-review", "Execute an LLM review pass (invoked by taskqueue)"),
    ]:
        r = sub.add_parser(name, help=helptext)
        add_project_args(r)
        r.add_argument("--locales", type=_csv, default=None)
        r.add_argument("--namespace", default=None)
        r.add_argument("--engine", default=None,
                         help="Use this engine for this run only (llm-localizator engine list); the config is not changed")
        r.add_argument("--model", default=None,
                       help="Reviewer model; default is the locale's translation model")
        r.add_argument("--batch-size", type=_positive_int, default=5, help="Keys per request")
        r.add_argument(
            "--keys", action="append", default=None, metavar="KEY",
            help="Explicit keys (namespace.key), repeatable or comma-separated",
        )
        r.add_argument("--dry-run", action="store_true")


def _add_sync_run_sync(sub: argparse._SubParsersAction) -> None:
    """Subcommands: sync / run-sync."""
    for name, helptext in [
        ("sync", "Scan + detect missing/stale (queue on_complete chains translate)"),
        ("run-sync", "Execute gather/sync (invoked by taskqueue or CI)"),
    ]:
        sy = sub.add_parser(name, help=helptext)
        add_project_args(sy)
        sy.add_argument("--locales", type=_csv, default=None)
        sy.add_argument("--dry-run", action="store_true",
                        help="Report backlog without writing or submitting")
        sy.add_argument("--no-translate", action="store_true",
                        help="Gather-only (default for queued run-sync; kept for overrides)")
        sy.add_argument("--submit-translate", action="store_true",
                        help="Also call tq to enqueue translate (prefer YAML on_complete)")
        sy.add_argument("--strict-branch", action="store_true",
                        help="Exit 1 when the checked-out branch is not [catalog] source_branch")
        sy.add_argument("--diff", action="store_true",
                        help="Write the work manifest (added / changed / removed keys)")
        sy.add_argument("--exit-nonzero", action="store_true",
                        help="With --diff: exit 1 when keys were added or changed (CI gate)")


def _add_improve_run_improve(sub: argparse._SubParsersAction) -> None:
    """Subcommands: improve / run-improve."""
    for name, helptext in [
        ("improve", "Submit overnight improve of low-score / flagged keys"),
        ("run-improve", "Execute improve pass (invoked by taskqueue)"),
    ]:
        im = sub.add_parser(name, help=helptext)
        add_project_args(im)
        im.add_argument("--locales", type=_csv, default=None)
        im.add_argument("--namespace", default=None)
        im.add_argument("--engine", default=None,
                         help="Use this engine for this run only (llm-localizator engine list); the config is not changed")
        im.add_argument("--model", default=None,
                        help="Improve model (default: [quality] improve_model or aya-expanse:8b)")
        im.add_argument("--limit", type=int, default=None,
                        help="Max keys per run (default: [quality] improve_limit)")
        im.add_argument(
            "--include-rejected",
            action="store_true",
            help=(
                "Retry keys whose last improve attempt was KEEP/FAIL "
                "(default: skip during cooldown so --limit batches rotate)"
            ),
        )
        im.add_argument(
            "--keys", action="append", default=None, metavar="KEY",
            help="Explicit keys (namespace.key), repeatable or comma-separated",
        )
        im.add_argument("--tag", dest="tags", action="append", default=None, metavar="TAG",
                        help="Only keys carrying this context tag (repeatable or comma-separated)")
        im.add_argument("--dry-run", action="store_true")


def _add_rescore_run_rescore(sub: argparse._SubParsersAction) -> None:
    """Subcommands: rescore / run-rescore."""
    for name, helptext in [
        ("rescore", "Submit a quality re-score job to taskqueue"),
        ("run-rescore", "Execute rescore (invoked by taskqueue)"),
    ]:
        rs = sub.add_parser(name, help=helptext)
        add_project_args(rs)
        rs.add_argument("--locales", type=_csv, default=None)
        rs.add_argument("--namespace", default=None)
        rs.add_argument("--engine", default=None,
                         help="Use this engine for this run only (llm-localizator engine list); the config is not changed")
        rs.add_argument("--model", default=None,
                        help="Override BT/score model (default: [quality] score_model / improve_model)")
        rs.add_argument("--dry-run", action="store_true",
                        help="List keys that would be rescored without calling the model")
        rs.add_argument("--stale-only", action="store_true",
                        help="Only keys with stale/missing/heuristic scores (requires --below-score)")
        rs.add_argument("--below-score", type=float, default=None, metavar="N",
                        help="Only keys with quality_score below N")
        rs.add_argument(
            "--keys", action="append", default=None, metavar="KEY",
            help="Explicit keys (namespace.key), repeatable or comma-separated",
        )


def _add_bakeoff_run_bakeoff(sub: argparse._SubParsersAction) -> None:
    """Subcommands: bakeoff / run-bakeoff."""
    for name, helptext in [
        ("bakeoff", "Compare local models on your own strings (evidence for ADR-12)"),
        ("run-bakeoff", "Execute bakeoff (invoked by taskqueue)"),
    ]:
        bo = sub.add_parser(name, help=helptext)
        add_project_args(bo)
        bo.add_argument("--locales", type=_csv, default=None,
                        help="Locales to test (default: the first active target)")
        bo.add_argument("--models", type=_csv, default=None,
                        help="Comma-separated Ollama tags (default: the pinned set plus the "
                             "locale's current model, which is always included)")
        bo.add_argument("--limit", type=int, default=30,
                        help="Keys to test, sampled evenly across UI roles (default 30)")
        bo.add_argument("--corpus", default=None,
                        help="A corpus JSON file, or 'builtin' (default: this project's strings)")
        bo.add_argument("--out", default=None,
                        help="Directory for REPORT.md / LEDGER.md (default: <state dir>/bakeoff)")
        bo.add_argument("--family", choices=["chat", "mt_chat"], default=None,
                        help="Prompt family (default: the project's)")
        bo.add_argument("--matrix", action="store_true",
                        help="Standard cells: stripped/chat, consumer/chat, consumer/mt_chat")
        bo.add_argument("--force-cells", action="store_true",
                        help="Re-run cells already in the ledger")
        bo.add_argument("--dry-run", action="store_true",
                        help="List the cells that would run; call no model")
        bo.add_argument("--propose-config", action="store_true",
                        help="Print a [locales.models] snippet from the Winners table of "
                             "REPORT.md (see --out); writes nothing, a human applies it")


def _add_export_import(sub: argparse._SubParsersAction) -> None:
    """Subcommands: export / import."""
    ex = sub.add_parser("export", help="Export catalogue for translators (CSV, XLIFF, JSON or xlsx)")
    add_project_args(ex)
    ex.add_argument("--collection", default=None,
                    help="Text collection (default: messages). Markdown export is the file.")
    ex.add_argument("--locales", type=_csv, default=None)
    ex.add_argument("--namespace", default=None, help="Restrict to a single namespace")
    ex.add_argument("--format", choices=["csv", "xliff", "json", "xlsx", "zip"], default="csv",
                    help="csv, xliff, json, or xlsx (needs the xlsx extra; one sheet per namespace). "
                         "zip is csv plus screenshots (same as --screenshots)")
    ex.add_argument("--only", default="all",
                    help="Row filter: all, untranslated, low_score, missing, stale, "
                         "machine, human, intentional, verified, unverified, unscored, "
                         "needs_better_model, or provider_*")
    ex.add_argument("--layout", choices=["single", "per-locale", "per-namespace"],
                    default="single",
                    help="single file, or a zip/directory with one file per locale or namespace")
    ex.add_argument("--xliff-version", choices=["1.2", "2.0"], default="1.2",
                    help="XLIFF flavour for --format xliff (2.0 needs one locale per file)")
    ex.add_argument("--bom", action="store_true",
                    help="Prefix CSV output with a UTF-8 BOM (Excel)")
    ex.add_argument("--screenshots", action="store_true",
                    help="Include context screenshots and a README (download is a zip)")
    ex.add_argument("--files", dest="file_count", type=int, default=1,
                    help="How many handoff files to write. 1 uses --layout. "
                         "2 or more splits the selected rows into that many files (a zip)")
    ex.add_argument("--approved-only", dest="approved_only", action="store_true",
                    help="Blank translations that are not verified (or reviewed, per [delivery] require)")
    ex.add_argument("--out", type=Path, default=None,
                    help="Output file or directory. Required for a split export or screenshots")
    ex.add_argument("--report", type=Path, default=None,
                    help="Write the JSON export report to this path")

    im = sub.add_parser("import", help="Import edited CSV, JSON, XLIFF or xlsx back into catalogues")
    add_project_args(im)
    im.add_argument("file", nargs="+", type=Path, help="Files from export (csv, json, xliff, xlsx, or zip)")
    im.add_argument("--format", choices=["csv", "xliff", "json"], default=None,
                    help="Input format when the name has no suffix (default: infer)")
    im.add_argument("--locales", type=_csv, default=None,
                    help="Locales to apply. Required for a headerless CSV")
    im.add_argument("--localized-by", dest="model", default="import",
                    help="Model name stamped on imported rows (provider stays import)")
    im.add_argument("--report", type=Path, default=None,
                    help="Write the JSON import report to this path")
    im.add_argument("--dry-run", action="store_true")

    cost = sub.add_parser(
        "estimate-cost",
        help="Maximum USD to localize due strings with a cloud provider (no API call)",
    )
    add_project_args(cost)
    cost.add_argument("--locales", type=_csv, default=None, metavar="LIST")
    cost.add_argument("--namespace", default=None)
    cost.add_argument("--collection", default=None)
    cost.add_argument(
        "--keys", action="append", default=None, metavar="KEY",
        help="Price only these keys (namespace.key) or remote unit ids",
    )
    cost.add_argument("--batch-size", type=_positive_int, default=None,
                      help="Keys per request (default: [translate] batch_size, else 10)")
    cost.add_argument("--purpose", choices=["translate", "review", "rescore"], default="translate",
                      help="translate prices due strings; review/rescore price judging every translated string")
    cost.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    report = sub.add_parser(
        "term-report",
        help="Glossary gaps and terms rendered inconsistently across keys (read-only)",
    )
    add_project_args(report)
    report.add_argument("--locales", help="Comma-separated target locales (default: all)")
    report.add_argument("--json", action="store_true", help="Print gaps and spreads as JSON")

    runtime = sub.add_parser(
        "runtime",
        help="Install, update or check the shipped browser i18n runtime in the consumer",
        description="Copy llm_localizator/web_runtime/i18n.js to [web] runtime_path "
                    "(install also writes an i18n.config.js template once). "
                    "check exits 1 when the copy is missing, edited or outdated.",
    )
    runtime.add_argument("action", choices=["install", "update", "check"])
    add_project_args(runtime)
    runtime.add_argument("--path", default=None,
                         help="Runtime path relative to the project root (overrides [web] runtime_path)")
    runtime.add_argument("--force", action="store_true",
                         help="Replace a file at the path that is not an llm-localizator runtime")
    runtime.add_argument("--json", action="store_true", help="Print the result as JSON")

    keys = sub.add_parser(
        "check-keys",
        help="Keys used in source vs the source catalogue, unused keys, stale en-XX (no LLM)",
        description="Scans [scan] src_dirs for i18n.t('key') and data-i18n* keys. "
                    "Exit 1 when a used key is missing or a QA locale is stale.",
    )
    add_project_args(keys)
    keys.add_argument("--strict", action="store_true", help="Also fail on unused keys")
    keys.add_argument("--no-qa", action="store_true", help="Skip the QA-locale (en-XX) staleness check")
    keys.add_argument("--json", action="store_true", help="Print the result as JSON")

    freeze = sub.add_parser(
        "release-freeze",
        help="Snapshot source hashes for a named release",
    )
    add_project_args(freeze)
    freeze.add_argument("--name", required=True)
    freeze.add_argument("--namespaces", default=None)
    freeze.add_argument("--keys", default=None)

    diff = sub.add_parser(
        "release-diff",
        help="Diff the current source against a release snapshot",
    )
    add_project_args(diff)
    diff.add_argument("--name", required=True)

    mcp = sub.add_parser("mcp", help="stdio MCP server for agents (optional mcp extra)")
    mcp.add_argument("--project", default=None, help="Unused. Tools take a project name.")
