"""CLI entry point.

**This is the only place terminal state is touched.** ``sys.stdout.reconfigure``
lives here and nowhere else -- calling it at module import (as the original
bridge script did) mutates the stdout encoding of any process that imports the
package, which is fine for a script and hostile for a library (F-008).
"""

from __future__ import annotations

import importlib
import sys

from ..projects import ConfigError
from ..catalog.mutation_lock import MutationLockTimeout
from ..providers.base import ProviderError
from .parsers import DEFAULT_MARKETING_PORT, DEFAULT_WEB_PORT, add_project_args, build_parser

# Parser builders live in ``cli/parsers/`` (one module per command group); these names stay importable from here.
# Default ports: web UI 8770, marketing site 8760, set in ``cli/parsers/common.py``.
__all__ = ["main", "build_parser", "add_project_args", "DEFAULT_WEB_PORT", "DEFAULT_MARKETING_PORT"]

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_WARNINGS = 2
EXIT_USAGE = 64


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - exotic terminals
                pass


_DIRECT_COMMANDS: dict[str, tuple[str, str]] = {
        "validate": ("cmd_validate", "run"),
        "quality": ("cmd_quality", "run"),
        "ingest-visual": ("cmd_ingest_visual", "run"),
        "status": ("cmd_status", "run"),
        "check": ("cmd_check", "run"),
        "concordance": ("cmd_tm", "run_concordance"),
        "tm-export": ("cmd_tm", "run_export"),
        "tm-import": ("cmd_tm", "run_import"),
        "org": ("cmd_org", "run"),
        "open-pr": ("cmd_open_pr", "run"),
        "screenshot-link": ("cmd_screenshot_link", "run"),
        "glossary-export": ("cmd_glossary", "run_export"),
        "glossary-import": ("cmd_glossary", "run_import"),
        "glossary-propose": ("cmd_glossary", "run_propose"),
        "impact": ("cmd_glossary", "run_impact"),
        "add-locale": ("cmd_add_locale", "run"),
        "hardcoded-hunt": ("cmd_hardcoded_hunt", "run"),
        "pseudo": ("cmd_glossary", "run_pseudo"),
        "analytics": ("cmd_analytics", "run"),
        "metrics": ("cmd_metrics", "run"),
        "workflow": ("cmd_workflow", "run"),
        "suggest": ("cmd_webui_ops", "run_suggest"),
        "draft": ("cmd_webui_ops", "run_draft"),
        "source-diff": ("cmd_webui_ops", "run_source_diff"),
        "task": ("cmd_webui_ops", "run_task"),
        "discuss": ("cmd_webui_ops", "run_discuss"),
        "flag-source": ("cmd_webui_ops", "run_flag_source"),
        "source-review-queue": ("cmd_webui_ops", "run_source_review_queue"),
        "bulk-clear": ("cmd_webui_ops", "run_bulk_clear"),
        "apply-near": ("cmd_webui_ops", "run_apply_near"),
        "find-replace": ("cmd_webui_ops", "run_find_replace"),
        "rename-placeholder": ("cmd_webui_ops", "run_rename_placeholder"),
        "scan-decide": ("cmd_webui_ops", "run_scan_decide"),
        "watch": ("cmd_watch", "run"),
        "hard-keys": ("cmd_hard_keys", "run"),
        "explain-scan": ("cmd_explain_scan", "run"),
        "adopt": ("cmd_adopt", "run"),
        "agent-backlog": ("cmd_agent_backlog", "run"),
        "agent-hardcoded": ("cmd_agent_hardcoded", "run"),
        "run-agent-hardcoded": ("cmd_agent_hardcoded", "run"),
        "patch": ("cmd_patch", "run"),
        "apply": ("cmd_apply", "run"),
        "discover": ("cmd_discover", "run"),
        "verify": ("cmd_verify", "run"),
        "projects": ("cmd_projects", "run"),
        "places": ("cmd_places", "run"),
        "web": ("cmd_web", "run"),
        "acknowledge-flush": ("cmd_acknowledge", "run"),
        "scan": ("cmd_scan", "run"),
        "migrate-state": ("cmd_migrate", "run"),
        "init": ("cmd_init", "run"),
        "approach": ("cmd_approach", "run"),
        "engine": ("cmd_engine", "run"),
        "queue-engine": ("cmd_queue_engine", "run"),
        "help": ("cmd_help", "run_help"),
        "set": ("cmd_help", "run_set"),
        "review-risk": ("cmd_help", "run_review_risk"),
        "cycle": ("cmd_help", "run_cycle"),
        "onboard": ("cmd_help", "run_onboard"),
        "context-propose": ("cmd_help", "run_context_propose"),
        "server-copy": ("cmd_help", "run_server_copy"),
        "glossary-learn": ("cmd_help", "run_glossary_learn"),
        "import-review": ("cmd_help", "run_import_review"),
        "context-note": ("cmd_help", "run_context_note"),
        "skill": ("cmd_help", "run_skill"),
        "guide": ("cmd_guide", "run"),
        "run-translate": ("cmd_translate", "run_execute"),
        "run-documents": ("cmd_documents", "run_documents"),
        "run-review": ("cmd_documents", "run_review_cmd"),
        "sync": ("cmd_sync", "run_submit"),
        "run-sync": ("cmd_sync", "run_execute"),
        "improve": ("cmd_improve", "run_submit"),
        "run-improve": ("cmd_improve", "run_execute"),
        "bakeoff": ("cmd_bakeoff", "run_submit"),
        "run-bakeoff": ("cmd_bakeoff", "run_execute"),
        "rescore": ("cmd_rescore", "run_submit"),
        "run-rescore": ("cmd_rescore", "run_execute"),
        "export": ("cmd_export", "export_cmd"),
        "import": ("cmd_export", "import_cmd"),
        "doctor": ("cmd_doctor", "run"),
        "estimate-cost": ("cmd_estimate_cost", "run"),
        "term-report": ("cmd_process", "run_term_report"),
        "runtime": ("cmd_web_runtime", "run_runtime"),
        "check-keys": ("cmd_web_runtime", "run_check_keys"),
        "release-freeze": ("cmd_process", "run_release_freeze"),
        "release-diff": ("cmd_process", "run_release_diff"),
        "mcp": ("cmd_mcp", "run"),
}


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    from ..projects import set_cli_branch

    set_cli_branch(getattr(args, "branch", None))
    if getattr(args, "engine", None):
        # One-run engine overlay (ADR-156): every load_config in this process (and its subprocesses) applies it.
        import os

        os.environ["LLM_LOCALIZE_ENGINE"] = args.engine

    if args.version:
        from .. import __version__

        print(__version__)
        return EXIT_OK

    if not args.command:
        parser.print_help()
        print("\nNew here? Run: llm-localizator guide")
        return EXIT_USAGE

    try:
        command = args.command
        if command in ("translate", "documents", "review"):
            module_name = "cmd_translate" if command == "translate" else "cmd_documents"
            module = importlib.import_module(f".{module_name}", __package__)
            return module.run_submit(args, command)
        module_name, function_name = _DIRECT_COMMANDS.get(command, (None, None))
        if module_name is not None:
            module = importlib.import_module(f".{module_name}", __package__)
            return getattr(module, function_name)(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERRORS
    except MutationLockTimeout as exc:
        print(f"error: another process holds the project mutation lock: {exc}", file=sys.stderr)
        return EXIT_ERRORS
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERRORS
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return 130

    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
