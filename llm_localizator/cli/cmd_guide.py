"""``llm-localizator guide`` -- what to do next, step by step.

On a terminal it is a loop: show the checklist, offer to do the next step, then
look again. Piped, or with ``--no-input``/``--json``, it only prints the checklist.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections.abc import Callable

from ..core.cldr import known_locales, language_name
from ..ops.add_locale import add_locale
from ..ops.guide import op_guide, run_smoke_test
from ..ops.types import GuideRequest
from ..projects import ConfigError, load_config, resolve
from ..projects.config import discover_config
from .prompt import PromptAborted, is_interactive, read_line

__all__ = ["run"]

_MAX_ROUNDS = 12


def _load(args: argparse.Namespace):
    """The project config, or ``None`` when this folder has none yet."""
    if args.project or args.config:
        return resolve(args.project, args.config)
    try:
        path = discover_config(args.directory)
    except ConfigError:
        return None
    return load_config(path)


def _confirm(input_fn: Callable[[str], str], question: str, *, default_yes: bool = True) -> bool:
    suffix = " [Y/n] " if default_yes else " [y/N] "
    answer = input_fn(question + suffix).strip().lower()
    if not answer:
        return default_yes
    return answer in ("y", "yes")


def _run_command(command: list[str]) -> int:
    """Run an external command, showing its output (patched in tests)."""
    return subprocess.run(command, check=False).returncode


def _act_environment(input_fn, **_ctx) -> bool:
    answer = input_fn("Start Ollama, then press Enter to check again (or type q to stop): ")
    return answer.strip().lower() not in ("q", "quit")


def _act_project(input_fn, args, cfg, **_ctx) -> bool:
    if cfg is not None:
        print("Add your source strings to the catalogue, then run the guide again.")
        return False
    from . import cmd_init
    from .main import build_parser

    if not _confirm(input_fn, "Create the project config now?"):
        return False
    init_args = build_parser().parse_args(
        ["init", *([args.directory] if args.directory else [])],
    )
    return cmd_init.run(init_args, input_fn=input_fn, interactive=True) == 0


def _act_approach(input_fn, cfg, step, **_ctx) -> bool:
    from ..ops.approaches import op_approach
    from ..projects.config import APPROACH_IDS

    default = (step.get("detail_vars") or {}).get("rec", "")
    raw = input_fn(f"How do you want to localize ({'/'.join(APPROACH_IDS)}) [{default}]: ").strip().lower()
    choice = raw or default
    if choice not in APPROACH_IDS:
        return False
    result = op_approach(cfg, set_to=choice, skip_probe=True)
    print(f"  {result.lines[0] if result.lines else result.summary}")
    return result.ok


def _act_languages(input_fn, cfg, **_ctx) -> bool:
    menu = ", ".join(f"{code} ({language_name(code)})" for code in known_locales())
    print(f"Languages you can pick from:\n  {menu}\nAny other language code works too.")
    raw = input_fn("Languages to translate into (codes, comma separated; Enter to stop): ")
    codes = [c.strip() for c in raw.replace(" ", ",").split(",") if c.strip()]
    if not codes:
        return False
    added = 0
    for code in codes:
        outcome = add_locale(cfg, code)
        if outcome.get("ok"):
            print(f"  added {code} ({language_name(code)})")
            added += 1
        else:
            print(f"  {code}: {outcome.get('error')}")
    return added > 0


def _act_model(input_fn, args, cfg, step, **_ctx) -> bool:
    if step["cli"] and step["cli"].startswith("ollama pull "):
        command = step["cli"]
        if not shutil.which("ollama"):
            print(f"Ollama is not installed. Install it from https://ollama.com, then run: {command}")
            return False
        if not _confirm(input_fn, f"Download the model now (`{command}`)?"):
            return False
        return _run_command(command.split()) == 0
    if cfg.provider.kind not in ("ollama", "null") and not args.yes:
        if not _confirm(
            input_fn,
            f"'{cfg.provider.kind}' is a paid provider. Send one short test string to it?",
            default_yes=False,
        ):
            return False
    if not _confirm(input_fn, "Run one quick test translation to confirm the model works?"):
        return False
    ok, message = run_smoke_test(cfg)
    print(f"  {message}")
    return ok


def _act_translate(input_fn, args, cfg, **_ctx) -> bool:
    paid = cfg.provider.kind not in ("ollama", "null")
    if paid:
        print(
            f"'{cfg.provider.kind}' is a paid provider. Check the price first with:\n"
            "  llm-localizator estimate-cost"
        )
        if not _confirm(input_fn, "Translate now?", default_yes=False):
            return False
    elif not _confirm(
        input_fn, "Translate now? This runs on your machine and can take a while.",
    ):
        return False
    from .main import main

    return main(["run-translate", "--config", str(cfg.config_path)]) == 0


def _act_review(input_fn, cfg, **_ctx) -> bool:
    print("Open the review editor with:  llm-localizator web")
    print("List the remaining problems with:  llm-localizator validate")
    return False


_ACTIONS: dict[str, Callable[..., bool]] = {
    "environment": _act_environment,
    "project": _act_project,
    "approach": _act_approach,
    "languages": _act_languages,
    "model": _act_model,
    "translate": _act_translate,
    "review": _act_review,
}


def run(
    args: argparse.Namespace,
    *,
    input_fn: Callable[[str], str] = read_line,
    interactive: bool | None = None,
) -> int:
    if interactive is None:
        interactive = is_interactive() and not args.json and not args.no_input
    try:
        return _run(args, input_fn, interactive)
    except PromptAborted:
        print("Stopped. Run `llm-localizator guide` whenever you want to continue.")
        return 0


def _run(args: argparse.Namespace, input_fn: Callable[[str], str], interactive: bool) -> int:
    cfg = _load(args)
    request = GuideRequest(
        directory=args.directory,
        smoke_test=args.smoke_test,
        skip_provider=args.skip_provider,
        yes=args.yes,
    )
    last: tuple[str, str] | None = None
    for _round in range(_MAX_ROUNDS):
        result = op_guide(cfg, request)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0
        next_id = result.data["next"]
        step = (
            next(s for s in result.data["steps"] if s["id"] == next_id) if next_id else None
        )
        if step is not None and last == (next_id, step["detail"]):
            print("That step is not finished yet. Do it with the command shown above, "
                  "then run `llm-localizator guide` again.")
            return 0
        for line in result.lines:
            print(line)
        if not interactive or step is None:
            return 0
        last = (next_id, step["detail"])
        act = _ACTIONS.get(next_id)
        print()
        if act is None or not act(input_fn=input_fn, args=args, cfg=cfg, step=step):
            return 0
        print()
        cfg = _load(args)
        # A one-off smoke test flag must not repeat on every round.
        request = GuideRequest(
            directory=args.directory,
            smoke_test=False,
            skip_provider=args.skip_provider,
            yes=args.yes,
        )
    return 0
