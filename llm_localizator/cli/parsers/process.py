"""Argparse builders: analytics, watch, metrics, workflow, suggest / source-review / bulk-clear family."""

from __future__ import annotations

import argparse

from .common import _csv, add_project_args


def _add_analytics(sub: argparse._SubParsersAction) -> None:
    """Subcommands: analytics."""
    an = sub.add_parser(
        "analytics",
        help="Summarize run speed from _runs/ manifests and verify/score lag",
    )
    add_project_args(an)
    an.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")
    an.add_argument("--since", default=None, help="ISO timestamp lower bound on started_at")
    an.add_argument(
        "--run-command",
        dest="run_command",
        choices=["translate", "improve", "review", "rescore"],
        default=None,
        help="Filter by pipeline command",
    )
    an.add_argument("--locale", default=None, help="Filter runs that include this locale")
    an.add_argument("--locales", type=_csv, default=None, help="Locales for lag report")
    an.add_argument("--model", default=None, help="Filter by pinned model")
    an.add_argument("--last", type=int, default=None, help="Show only the N most recent runs")


def _add_watch(sub: argparse._SubParsersAction) -> None:
    """Subcommands: watch."""
    wa = sub.add_parser(
        "watch",
        help="Foreground: re-run sync when a source catalogue file changes (not a daemon)",
    )
    add_project_args(wa)
    wa.add_argument("--interval", type=float, default=5.0, help="Poll seconds (default 5)")
    wa.add_argument("--diff", action="store_true", help="Also write the work manifest each time")


def _add_metrics(sub: argparse._SubParsersAction) -> None:
    """Subcommands: metrics."""
    mt = sub.add_parser(
        "metrics",
        help="Edit rate, cycle time and coverage trend from history",
    )
    add_project_args(mt)
    mt.add_argument("--format", dest="fmt", choices=["text", "json", "csv"], default="text",
                    help="Output format; csv needs --by")
    mt.add_argument("--by", choices=["user", "locale", "locale+user"], default=None,
                    help="Activity report: count edits per user, per locale or both instead of edit rate")
    mt.add_argument("--since", default=None, help="Window such as 30d, 12h, 2w, or an ISO date")
    mt.add_argument("--locale", default=None, help="One locale")
    mt.add_argument("--locales", type=_csv, default=None, help="Several locales")
    mt.add_argument("--why-low", action="store_true",
                    help="Group low-scored keys by weakest quality dimension instead of edit rate")
    mt.add_argument("--threshold", type=float, default=None,
                    help="With --why-low: score below which a key counts as low (default 0.55)")


def _add_workflow(sub: argparse._SubParsersAction) -> None:
    """Subcommands: workflow."""
    wf = sub.add_parser("workflow", help="Run a named workflow script (route, improve, review)")
    add_project_args(wf)
    wf.add_argument("--name", dest="workflow_name", default="default", help="Workflow name (default: default)")
    wf.add_argument("--locales", type=_csv, default=None, help="Limit to these locales")
    wf.add_argument("--namespace", default=None)
    wf.add_argument("--dry-run", action="store_true", help="Count what each block would do")
    wf.add_argument("--route-only", action="store_true", help="Only route keys; no LLM work")
    wf.add_argument("--submit", action="store_true", help="Submit LLM blocks to the taskqueue")
    wf.add_argument("--inline", action="store_true", help="Run LLM blocks in this process")
    wf.add_argument("--resume", default=None, metavar="RUN_ID", help="Continue a waiting run")
    wf.add_argument("--list-presets", action="store_true", help="List the built-in starting scripts and exit")
    wf.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")


def _add_suggest_source_review_bulk_clear(sub: argparse._SubParsersAction) -> None:
    """Subcommands: suggest / source review / bulk-clear."""
    dr = sub.add_parser(
        "draft",
        help="Keep model suggestions as drafts until a person accepts them (nothing is written by create)",
    )
    add_project_args(dr)
    dr.add_argument("action", choices=["list", "create", "accept", "reject"], nargs="?", default="list")
    dr.add_argument("--locale", default=None)
    dr.add_argument("--namespace", default=None)
    dr.add_argument("--key", default=None)
    dr.add_argument("--keys", type=_csv, default=None,
                    help="Several keys (namespace.key, comma-separated) for accept or reject")
    dr.add_argument("--by", default="", help="Who made the draft (default: cli)")
    dr.add_argument("--mode", choices=["minimal-edit"], default=None,
                    help="create only: edit the existing translation after a source change instead of retranslating (opt-in model call)")
    dr.add_argument("--confirm", action="store_true",
                    help="accept only: overwrite a translation a person edited (otherwise it is skipped)")
    dr.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    sl = sub.add_parser(
        "screenshot-link",
        help="Attach screenshots to keys, with optional highlighted regions",
        description="list (default), link or unlink. A region is x,y,w,h as fractions of the image (0..1).",
    )
    add_project_args(sl)
    sl.add_argument("action", choices=["list", "link", "unlink"], nargs="?", default="list")
    sl.add_argument("--file", default=None, help="link: image path relative to the context folder")
    sl.add_argument("--namespace", default=None)
    sl.add_argument("--key", default=None)
    sl.add_argument("--region", default=None, help="link: x,y,w,h as fractions, e.g. 0.1,0.2,0.3,0.1")
    sl.add_argument("--note", default=None)
    sl.add_argument("--link", default=None, help="unlink: the link id")
    sl.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    pr = sub.add_parser(
        "open-pr",
        help="Plan, open or check a pull request for changed catalogue files",
        description="Needs [git_host] enabled = true. plan (default) writes nothing; open creates a branch, "
                    "commits the catalogue files, pushes and runs gh pr create, and needs --yes.",
    )
    add_project_args(pr)
    pr.add_argument("action", choices=["plan", "open", "status"], nargs="?", default="plan")
    pr.add_argument("--pr-branch", dest="pr_branch", default=None, help="status: the branch whose PR to check")
    pr.add_argument("--yes", action="store_true", help="open: confirm the push and PR")
    pr.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    sd = sub.add_parser(
        "source-diff",
        help="Show what changed in one source string and which words need translating",
        description="Read-only. Uses the source-change log; run sync first to record a change.",
    )
    add_project_args(sd)
    sd.add_argument("--locale", default=None, help="Show this locale's current translation too")
    sd.add_argument("--namespace", default=None)
    sd.add_argument("--key", default=None)
    sd.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    dc = sub.add_parser(
        "discuss",
        help="Per-key discussion threads with @mentions and a resolved state",
    )
    add_project_args(dc)
    dc.add_argument("action", choices=["list", "add", "resolve", "reopen"], nargs="?", default="list")
    dc.add_argument("--namespace", default=None)
    dc.add_argument("--key", default=None)
    dc.add_argument("--text", default=None, help="Comment text (add); @name mentions a person")
    dc.add_argument("--mention", default=None, help="List only threads that mention this person")
    dc.add_argument("--open-only", dest="open_only", action="store_true",
                    help="List only unresolved threads")
    dc.add_argument("--by", default="", help="Who is commenting (default: cli)")
    dc.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    tk = sub.add_parser(
        "task",
        help="Work packages of keys with one assignee per locale and a due date",
    )
    add_project_args(tk)
    tk.add_argument("action", choices=["list", "create", "delete"], nargs="?", default="list")
    tk.add_argument("--id", default=None, help="Task id (delete)")
    tk.add_argument("--name", default=None, help="Task name (create)")
    tk.add_argument("--namespace", default=None, help="Take every key of this namespace")
    tk.add_argument("--keys", type=_csv, default=None, help="Keys (namespace.key, comma-separated)")
    tk.add_argument("--assign", type=_csv, default=None,
                    help="Who does which locale, e.g. pl=anna,de=ben")
    tk.add_argument("--due", default=None, help="Due date, YYYY-MM-DD")
    tk.add_argument("--unverified", action="store_true",
                    help="Keep only keys not yet verified in an assigned locale")
    tk.add_argument("--assignee", default=None, help="List only tasks for this person")
    tk.add_argument("--by", default="", help="Who created the task (default: cli)")
    tk.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    sg = sub.add_parser("suggest", help="Show one model translation for a key without saving it")
    add_project_args(sg)
    sg.add_argument("--locale", required=True)
    sg.add_argument("--namespace", required=True)
    sg.add_argument("--key", required=True)
    sg.add_argument(
        "--explain", action="store_true",
        help="Also list what fed the prompt: context, glossary hits, TM and catalogue examples, notes",
    )
    sg.add_argument(
        "--alternatives", action="store_true",
        help="Also ask up to two other configured models (secondary role, roster default) for their version; not for cloud projects",
    )
    sg.add_argument(
        "--ambiguity", action="store_true",
        help="Also ask the model which source terms have several senses and which it chose (advisory; not for cloud projects)",
    )
    sg.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    fs = sub.add_parser("flag-source", help="Flag an English string for source review")
    add_project_args(fs)
    fs.add_argument("--namespace", required=True)
    fs.add_argument("--key", required=True)
    fs.add_argument("--note", default="")

    sq = sub.add_parser("source-review-queue", help="List English strings flagged for review")
    add_project_args(sq)
    sq.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    bc = sub.add_parser(
        "bulk-clear",
        help="Send stale or old machine translations back to the backlog (human keys are kept)",
    )
    add_project_args(bc)
    bc.add_argument("--locale", default=None)
    bc.add_argument("--locales", type=_csv, default=None)
    bc.add_argument("--namespace", default=None)
    bc.add_argument("--stale-to-source", action="store_true",
                    help="Clear keys whose English changed since they were translated")
    bc.add_argument("--purge-machine-older-than", type=int, default=None, metavar="DAYS",
                    help="Clear machine translations older than DAYS days")
    bc.add_argument("--invalid", action="store_true",
                    help="Clear translations that fail a hard check (stray backslash, foreign script, "
                         "placeholder/HTML/literal mismatch). Import- and agent-made rows count; web edits do not")
    bc.add_argument("--latin-leftover", dest="latin_leftover", action="store_true",
                    help="Clear non-Latin translations that carry Latin words the source does not")
    bc.add_argument("--dry-run", action="store_true")
    bc.add_argument("--confirm", action="store_true", help="Apply (default only lists)")

    an = sub.add_parser(
        "apply-near",
        help="Copy one edited translation onto similar keys you name (preview unless --confirm)",
    )
    add_project_args(an)
    an.add_argument("--locale", required=True)
    an.add_argument("--namespace", required=True)
    an.add_argument("--key", required=True, help="The key whose translation to copy")
    an.add_argument("--min-similarity", type=float, default=0.85,
                    help="Smallest English-text similarity, 0 to 1 (default 0.85)")
    an.add_argument("--keys", type=_csv, default=None,
                    help="Targets to write (namespace.key, comma-separated); without it only lists")
    an.add_argument("--dry-run", action="store_true")
    an.add_argument("--confirm", action="store_true", help="Apply (default only lists)")
    an.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    fr = sub.add_parser(
        "find-replace",
        help="Find and replace text in one locale's translations (preview unless --confirm)",
    )
    add_project_args(fr)
    fr.add_argument("--locale", required=True)
    fr.add_argument("--find", required=True, help="Literal text to find")
    fr.add_argument("--replace", default="", help="Replacement text (default empty)")
    fr.add_argument("--namespace", default=None)
    fr.add_argument("--case-sensitive", action="store_true")
    fr.add_argument("--keys", type=_csv, default=None,
                    help="Keys to change (namespace.key, comma-separated); without it only lists")
    fr.add_argument("--dry-run", action="store_true")
    fr.add_argument("--confirm", action="store_true", help="Apply (default only lists)")
    fr.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")

    rp = sub.add_parser(
        "rename-placeholder",
        help="Rename {old} to {new} in the English text and every translation (no re-translation)",
    )
    add_project_args(rp)
    rp.add_argument("--old", required=True, help="Current placeholder name, without braces")
    rp.add_argument("--new", required=True, help="New placeholder name, without braces")
    rp.add_argument("--namespace", default=None)
    rp.add_argument("--keys", type=_csv, default=None,
                    help="Only these keys (namespace.key, comma-separated)")
    rp.add_argument("--dry-run", action="store_true")
    rp.add_argument("--confirm", action="store_true", help="Apply (default only lists the edits)")
