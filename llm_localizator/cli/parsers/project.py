"""Argparse builders: web, doctor, scan, projects, places, status and the commands defined with it."""

from __future__ import annotations

import argparse
from pathlib import Path

from .common import add_project_args, DEFAULT_WEB_PORT, DEFAULT_MARKETING_PORT


def _add_web(sub: argparse._SubParsersAction) -> None:
    """Subcommands: web."""
    w = sub.add_parser("web", help="Browse and edit translations in a local web UI")
    add_project_args(w)
    w.add_argument("--port", type=int, default=DEFAULT_WEB_PORT)
    w.add_argument(
        "--marketing-port",
        type=int,
        default=DEFAULT_MARKETING_PORT,
        help="Loopback marketing site port (default: 8760; ADR-45)",
    )
    w.add_argument(
        "--no-marketing",
        action="store_true",
        help="Do not bind the marketing site (app port only)",
    )
    w.add_argument("--no-browser", action="store_true",
                   help="Do not open a browser window")
    w.add_argument("--paranoid", action="store_true",
                   help="Force cloud off, cross-origin edit off, and escaped HTML preview")

    af = sub.add_parser(
        "acknowledge-flush",
        help="Delete an interrupted flush journal without writing catalogues",
    )
    add_project_args(af)

    dr = sub.add_parser(
        "doctor",
        help="Check install, config, Ollama, and whether the web UI is up to date",
    )
    add_project_args(dr)
    dr.add_argument("--port", type=int, default=DEFAULT_WEB_PORT,
                    help="Web port to probe (default: 8770)")
    dr.add_argument("--skip-ollama", action="store_true",
                    help="Skip Ollama connectivity check")
    dr.add_argument("--json", action="store_true", help="Machine-readable output")


def _add_scan(sub: argparse._SubParsersAction) -> None:
    """Subcommands: scan."""
    sc = sub.add_parser("scan", help="Find t() call sites and hardcoded strings (no LLM)")
    add_project_args(sc)
    sc.add_argument("--adapter", default=None, help="Override the configured scan adapter")
    sc.add_argument("--out-dir", type=Path, default=None, help="Where to write usage artefacts")
    sc.add_argument("--no-write", action="store_true", help="Report only; write nothing")
    sc.add_argument("--format", dest="fmt", choices=["text", "github", "json"], default="text")
    sc.add_argument("--strict", action="store_true",
                    help="Exit 1 if any hardcoded string is found")
    sc.add_argument("--lint-directives", action="store_true",
                    help="Report stale or malformed l10n-ignore comments (exit 1 if any)")

    disc = sub.add_parser(
        "discover",
        help="Propose text collections from locale-named directories (writes nothing)",
    )
    add_project_args(disc)
    disc.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    ver = sub.add_parser(
        "verify",
        help="Run the verification workflow on a disposable copy of a project",
    )
    ver.add_argument("path", nargs="?", default=".", help="Project directory (never modified)")
    ver.add_argument("--profile", choices=["quick", "standard", "deep"], default="quick")
    ver.add_argument("--locales", default=None, help="Named locale set (deep profile)")
    ver.add_argument("--out", default=None, help="Run output directory")
    ver.add_argument("--resume", default=None, help="Resume a run id")
    ver.add_argument("--only", default=None, help="Comma-separated stage ids")
    ver.add_argument("--skip", default=None, help="Comma-separated stage ids")
    ver.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")


def _add_projects(sub: argparse._SubParsersAction) -> None:
    """Subcommands: projects."""
    pr = sub.add_parser("projects", help="List, rename, remove or prune registered projects")
    pr.add_argument("action", nargs="?", choices=["list", "remove", "rename", "prune"], default="list")
    pr.add_argument("names", nargs="*", help="remove NAME | rename OLD NEW")
    pr.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")


def _add_places(sub: argparse._SubParsersAction) -> None:
    """Subcommands: places (ADR-104)."""
    pl = sub.add_parser("places", help="List or set the translation policy per text place")
    add_project_args(pl)
    pl.add_argument("action", nargs="?", choices=["list", "set", "unset"], default="list")
    pl.add_argument("place", nargs="?", default="", help="namespace glob, optionally NS:KEYGLOB")
    pl.add_argument("--policy", choices=["auto", "request", "review", "never"], default="")
    pl.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")


def _add_status(sub: argparse._SubParsersAction) -> None:
    """Subcommands: status."""
    s = sub.add_parser("status", help="Show per-locale translation coverage (no LLM)")
    add_project_args(s)
    s.add_argument("--collection", default=None,
                   help="Text collection (default: messages). File collections list paths. "
                        "A remote collection reports source language and coverage.")
    s.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")
    s.add_argument("--missing", action="store_true",
                   help="List keys that are missing or stale per locale (instead of summary)")
    s.add_argument("--by-screen", action="store_true",
                   help="Group coverage by the screen named in each key's context note")

    chk = sub.add_parser("check", help="CI gate: exit 1 when translations are stale or incomplete (no LLM)")
    add_project_args(chk)
    chk.add_argument("--locales", default=None, help="Comma-separated locales to check (default: all)")
    chk.add_argument("--min-coverage", type=float, default=1.0,
                     help="Required coverage per locale, 0-1 (default 1.0)")
    chk.add_argument("--allow-stale", action="store_true", help="Do not fail on stale translations")
    chk.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    conc = sub.add_parser("concordance", help="Search the translation memory (no LLM)")
    add_project_args(conc)
    conc.add_argument("--locale", required=True)
    conc.add_argument("--query", required=True)
    conc.add_argument("--no-source", action="store_true", help="Do not search source text")
    conc.add_argument("--no-target", action="store_true", help="Do not search translations")
    conc.add_argument("--limit", type=int, default=20)
    conc.add_argument(
        "--min-similarity", type=float, default=None, metavar="0.1-1",
        help="Fuzzy search by word overlap instead of substring; keep matches at or above this share (try 0.55)",
    )
    conc.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    tmx_out = sub.add_parser("tm-export", help="Write one locale's translation memory as TMX")
    add_project_args(tmx_out)
    tmx_out.add_argument("--locale", required=True)
    tmx_out.add_argument("--out", default=None, help="File to write; stdout when omitted")

    tmx_in = sub.add_parser("tm-import", help="Merge a TMX file into the translation memory")
    add_project_args(tmx_in)
    tmx_in.add_argument("--locale", required=True)
    tmx_in.add_argument("--file", required=True)
    tmx_in.add_argument(
        "--conflict",
        choices=["skip", "overwrite-if-higher", "always"],
        default="skip",
    )
    tmx_in.add_argument("--dry-run", action="store_true", help="Count changes and write nothing")

    org = sub.add_parser(
        "org",
        help="Show whether this project uses the organisation-level TM and glossary",
        description="Read-only. Enable with [org] use = true in the project config; "
                    "contribute = true also writes approved text to the organisation TM.",
    )
    add_project_args(org)
    org.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    g_out = sub.add_parser("glossary-export", help="Write the glossary as CSV or TBX")
    add_project_args(g_out)
    g_out.add_argument("--format", choices=["csv", "tbx"], default="csv")
    g_out.add_argument("--file", default=None, help="File to write; stdout when omitted")

    g_in = sub.add_parser("glossary-import", help="Merge a CSV or TBX glossary")
    add_project_args(g_in)
    g_in.add_argument("--file", default=None)
    g_in.add_argument("--format", choices=["csv", "tbx"], default=None)
    g_in.add_argument("--conflict", choices=["skip", "overwrite"], default="skip")
    g_in.add_argument("--dry-run", action="store_true", help="Parse and write nothing")

    g_prop = sub.add_parser("glossary-propose", help="Print candidate glossary terms (writes nothing)")
    add_project_args(g_prop)
    g_prop.add_argument("--locale", default=None,
                        help="Mine this locale's translation memory; prints a glossary-import CSV")
    g_prop.add_argument("--min-occurrences", dest="min_occurrences", type=int, default=5,
                        help="With --locale: entries a term must appear in (default 5)")
    g_prop.add_argument("--out", default=None, help="With --locale: write the CSV here")

    impact = sub.add_parser("impact", help="List locales stale because the source hash changed")
    add_project_args(impact)

    add_loc = sub.add_parser(
        "add-locale",
        help="Add a target locale to the project config (no LLM)",
    )
    add_project_args(add_loc)
    add_loc.add_argument("--locale", required=True, help="Locale code to append to [locales] targets")
    add_loc.add_argument("--model", default=None, help="Optional [locales.models] entry for this locale")

    hunt = sub.add_parser(
        "hardcoded-hunt",
        help="Pseudo en-XX, crawl leftovers (dogfood presets or [qa]), refresh agent-hardcoded",
    )
    add_project_args(hunt)
    hunt.add_argument(
        "--skip-crawl", action="store_true",
        help="Skip Playwright crawl/intersect (pseudo + optional static only)",
    )
    hunt.add_argument(
        "--skip-static", action="store_true",
        help="Skip agent-hardcoded --refresh after the visual pass",
    )
    hunt.add_argument(
        "--serve", action="store_true",
        help="Let crawl.py start its own web server (default: --no-serve)",
    )
    hunt.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    pseudo = sub.add_parser("pseudo", help="Write a throwaway expanded locale (no state)")
    add_project_args(pseudo)
    pseudo.add_argument("--locale", default="en-XA")
    pseudo.add_argument("--length-factor", dest="length_factor", type=float, default=1.4)
    pseudo.add_argument(
        "--style", default="",
        help="accents (en-XA pad) or xxxx (en-XX marker Xs); default from locale",
    )
