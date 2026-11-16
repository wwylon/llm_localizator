"""Argparse builders: quality, validate, ingest-visual."""

from __future__ import annotations

import argparse

from .common import add_project_args, _positive_int


def _add_quality(sub: argparse._SubParsersAction) -> None:
    """Subcommands: quality."""
    q = sub.add_parser(
        "quality",
        help="One-shot quality report for a project or for message files (no registration)",
        description=(
            "Run every catalogue check, and optionally the LLM scorer, and print a "
            "per-locale report. With --path-template it works on files you name and "
            "writes nothing to them."
        ),
    )
    add_project_args(q)
    q.add_argument("--path-template", default=None, metavar="TEMPLATE",
                   help="Message files relative to --root, with {locale} and optionally "
                        "{namespace}. Without it the project config is used.")
    q.add_argument("--root", default=None, metavar="DIR",
                   help="Directory the path template is relative to (default: current directory)")
    q.add_argument("--catalog-format", default=None, metavar="NAME",
                   help="Catalogue adapter for --path-template (default: json-nested)")
    q.add_argument("--source", default=None, metavar="CODE",
                   help="Source locale for --path-template")
    q.add_argument("--target", dest="targets", action="append", default=None, metavar="CODE",
                   help="Target locale for --path-template; repeatable")
    q.add_argument("--locale", action="append", dest="locales", metavar="CODE",
                   help="Restrict the report to this locale; repeatable")
    q.add_argument("--score", action="store_true",
                   help="Also score translations with the judge model (needs Ollama; cloud rules apply)")
    q.add_argument("--model", default=None, help="Judge model for --score")
    q.add_argument("--limit", type=_positive_int, default=50,
                   help="Findings to list in text output (default 50)")
    q.add_argument("--format", dest="fmt", choices=["text", "json"], default="text",
                   help="Output format")


def _add_validate(sub: argparse._SubParsersAction) -> None:
    """Subcommands: validate."""
    v = sub.add_parser(
        "validate",
        help="Check catalogues for ICU, plural, glossary, and staleness problems (no LLM)",
        description="Run every catalogue check. Needs no Ollama, no GPU, and no network.",
    )
    add_project_args(v)
    v.add_argument("--locale", action="append", dest="locales", metavar="CODE",
                   help="Restrict to this locale; repeatable. Default: all configured targets.")
    v.add_argument("--namespace", default=None, help="Restrict to a single namespace")
    v.add_argument("--format", dest="fmt", choices=["text", "github", "json"], default="text",
                   help="Output format. 'github' emits workflow annotations.")
    v.add_argument("--strict", action="store_true",
                   help="Treat warnings as errors (exit 1 instead of 2)")
    v.add_argument("--check-expansion", action="store_true",
                   help="Also run the V14 expansion-band check. Off by default: it "
                        "compares character counts against bands authored for rendered "
                        "width, which is very noisy for Arabic and CJK. "
                        "--semantic turns this on as well.")
    v.add_argument("--check-numbers", action="store_true",
                   help="Also run V38, the locale number and date-order check. "
                        "Off by default.")
    v.add_argument("--diff-only", action="store_true",
                   help="Skip keys that validated clean last run with identical "
                        "text, context, state and check flags. Keys with findings "
                        "are always re-checked.")
    v.add_argument("--semantic", action="store_true",
                   help="Also run semantic advisory checks (V17 whitespace parity, "
                        "V21 script family, V22 maxChars, V23 word-count band, "
                        "V24 fullKey coherence, V30/V31 catalogue coherence).")
    v.add_argument("--diff-scope", nargs="*", default=None, metavar="FILE",
                   help="Only check namespaces touching these files. With no arguments, "
                        "reads the list from stdin (one path per line).")
    v.add_argument("--unused", action="store_true",
                   help="Also report V41: source keys that no scanned code references. "
                        "Needs [scan] adapter and src_dirs; runs the source scanner, so "
                        "it is off by default. Keys matching [scan] unused_allow are "
                        "skipped. A warning; --strict makes it fail.")
    v.add_argument("--quiet", action="store_true", help="Print only the summary line")
    v.add_argument(
        "--write-flags",
        action="store_true",
        help="Append V13 (and V06) findings to the project's flags file for improve",
    )
    v.add_argument(
        "--flag-checks",
        default="V13",
        metavar="LIST",
        help="Comma-separated check ids to flag with --write-flags (default: V13)",
    )
    v.add_argument(
        "--check-layout",
        action="store_true",
        help="Advisory V28 layout QA when a screenshot is attached via context "
             "screen/image (maxChars, expansion, script, PNG heuristics).",
    )


def _add_ingest_visual(sub: argparse._SubParsersAction) -> None:
    """Subcommands: ingest-visual."""
    iv = sub.add_parser(
        "ingest-visual",
        help="Load consumer visual findings JSONL into the review queue (no LLM)",
        description="See docs/visual-findings.md and ADR-27.",
    )
    add_project_args(iv)
    iv.add_argument(
        "--path",
        default=None,
        help="Findings JSONL path (default: derived from context_dir / [visual] findings_path)",
    )
    iv.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print tickets without writing the review queue",
    )
