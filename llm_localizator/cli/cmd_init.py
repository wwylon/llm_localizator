"""``llm-localizator init`` -- detect a project's layout and write its config."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from ..core.cldr import known_locales, language_name
from ..ops.guide import ollama_state
from ..ops.init import op_init
from ..ops.types import InitRequest
from ..projects.init_layout import DEFAULT_DOMAIN, DEFAULT_MODEL, detect_layout
from .prompt import PromptAborted, is_interactive, read_line

__all__ = ["run", "detect_layout"]


def _ask(input_fn: Callable[[str], str], question: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    answer = input_fn(f"{question}{hint}: ").strip()
    return answer or default


def _language_menu() -> str:
    codes = known_locales()
    return ", ".join(f"{code} ({language_name(code)})" for code in codes)


def _split(text: str) -> list[str]:
    return [piece.strip() for piece in text.replace(" ", ",").split(",") if piece.strip()]


def _prompt_missing(
    args: argparse.Namespace, input_fn: Callable[[str], str],
) -> dict:
    """Ask only for what the flags left out."""
    answers: dict = {}
    ollama_up: bool | None = None
    print("Let's set up your project. Press Enter to accept the value in [brackets].\n")

    source = args.source_locale
    if source == "en":
        source = _ask(input_fn, "Language your strings are written in", "en")
    answers["source_locale"] = source

    if args.targets is None:
        print(f"\nLanguages you can pick from:\n  {_language_menu()}")
        print("Any other language code works too.")
        raw = _ask(input_fn, "Languages to translate into (codes, comma separated)", "")
        answers["targets"] = _split(raw)
        if not answers["targets"]:
            print("  No languages yet. Add one later with: llm-localizator add-locale --locale pl")

    if args.model is None:
        up, installed = ollama_state("http://localhost:11434")
        ollama_up = up
        default_model = DEFAULT_MODEL
        if up and installed:
            print(f"\nModels installed in Ollama: {', '.join(installed)}")
            if not any(name.split(":")[0] == DEFAULT_MODEL for name in installed):
                default_model = installed[0]
        answers["model"] = _ask(input_fn, "Model that translates", default_model)

    if args.domain is None:
        answers["domain"] = _ask(
            input_fn, "\nOne sentence about your product (helps terminology)", DEFAULT_DOMAIN,
        )
    if getattr(args, "approach", None) is None:
        from ..ops.approaches import APPROACHES, probe, recommend

        rec, reason = recommend(probe(None, ollama_up=ollama_up, skip=ollama_up is None))
        print("\nWho should write the translations?")
        for a in APPROACHES:
            print(f"  {a.id:<7} {a.title} ({a.cost})")
        print(f"Recommended here: {rec} ({reason}).")
        choice = _ask(input_fn, "Approach", rec).strip().lower()
        answers["approach"] = choice if choice in {a.id for a in APPROACHES} else rec
    return answers


def run(
    args: argparse.Namespace,
    *,
    input_fn: Callable[[str], str] = read_line,
    interactive: bool | None = None,
) -> int:
    if interactive is None:
        interactive = is_interactive() and not args.yes
    try:
        answers = _prompt_missing(args, input_fn) if interactive else {}
    except PromptAborted:
        print("Stopped before writing anything. Run `llm-localizator init --yes` to accept the defaults.")
        return 1

    result = op_init(InitRequest(
        directory=args.directory,
        name=args.name,
        source_locale=answers.get("source_locale", args.source_locale),
        catalog_format=getattr(args, "catalog_format", None),
        catalog_path=getattr(args, "catalog_path", None),
        taskqueue=args.taskqueue,
        no_register=args.no_register,
        force=args.force,
        targets=args.targets if args.targets is not None else answers.get("targets"),
        model=args.model or answers.get("model"),
        domain=args.domain or answers.get("domain"),
        provider=args.provider,
        approach=getattr(args, "approach", None) or answers.get("approach"),
    ))
    for line in result.lines:
        print(line)
    if not result.ok and result.exit_code == 1 and "already exists" in result.summary:
        print("Use --force to overwrite, or --taskqueue to regenerate the blueprint.")
    if result.ok:
        print("\nNext: run `llm-localizator guide` to see the remaining steps.")
    return result.exit_code
