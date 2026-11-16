"""``llm-localizator help`` and ``llm-localizator skill`` (ADR-121)."""

from __future__ import annotations

import argparse
import sys

from ..help import guide_path, guide_text

__all__ = ["run_help", "run_skill", "run_set", "run_review_risk", "run_cycle", "run_onboard", "run_context_propose", "run_context_note", "run_server_copy",
           "run_glossary_learn", "run_import_review"]


def run_help(args: argparse.Namespace) -> int:
    if getattr(args, "regenerate", False):
        from ..help.blocks import regenerate_files

        changed = regenerate_files()
        print(f"regenerated: {', '.join(changed)}" if changed else "guides already current")
        return 0
    from ..help.topics import code_text, code_topic_names, lang_text, lang_topic_names

    if getattr(args, "topics", False):
        print("--code: " + ", ".join(code_topic_names()))
        print("--lang: " + ", ".join(lang_topic_names()))
        return 0
    if args.code or args.lang:
        reader = args.guide or "human"
        try:
            text = code_text(args.code, reader) if args.code else lang_text(args.lang, reader)
        except (ValueError, OSError) as exc:
            print(f"help: {exc}", file=sys.stderr)
            return 2
        try:
            sys.stdout.write(text)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(text.encode("utf-8"))
        return 0
    if not args.guide:
        print("usage: llm-localizator help {human,agent} [--path] [--code TOPIC | --lang CODE | --topics] | --regenerate",
              file=sys.stderr)
        return 2
    if args.path:
        print(guide_path(args.guide))
        return 0
    text = guide_text(args.guide)
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:  # a legacy console code page
        sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


def run_skill(args: argparse.Namespace) -> int:
    from ..ops.skill import op_skill
    from ..projects import resolve

    cfg = resolve(args.project, args.config)
    result = op_skill(cfg, args.action, force=bool(getattr(args, "force", False)))
    print(result.summary)
    return result.exit_code


def run_set(args: argparse.Namespace) -> int:
    from ..ops.set_translation import op_set
    from ..projects import resolve

    cfg = resolve(args.project, args.config)
    result = op_set(cfg, locale=args.locale, key=args.key, text=args.text, by=args.by,
                    model=args.model, force=args.force)
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code


def run_review_risk(args: argparse.Namespace) -> int:
    import json

    from ..ops.review_risk import op_review_risk
    from ..projects import resolve

    cfg = resolve(args.project, args.config)
    result = op_review_risk(cfg, locale=args.locale, limit=args.limit, fmt=args.fmt)
    if args.fmt == "json":
        print(json.dumps(result.data, ensure_ascii=False, indent=2))
        return result.exit_code
    if args.fmt == "text":
        print(result.summary)
    text = "\n".join(result.lines) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))
    return result.exit_code


def run_cycle(args: argparse.Namespace) -> int:
    from ..ops.cycle import op_cycle
    from ..ops.types import parse_csv_list
    from ..projects import resolve

    cfg = resolve(args.project, args.config)
    result = op_cycle(cfg, locales=parse_csv_list(args.locales), translate=args.translate,
                      repair=args.repair, review_limit=args.review_limit,
                      follow=getattr(args, "follow", False),
                      follow_timeout=getattr(args, "follow_timeout", 3600.0))
    print(result.summary)
    return result.exit_code


def run_onboard(args: argparse.Namespace) -> int:
    from ..ops.onboard import op_onboard

    result = op_onboard(args.directory, targets=args.targets, frozen=args.frozen,
                        approach=args.approach, runtime_path=args.runtime_path,
                        install_runtime=args.install_runtime, no_register=args.no_register)
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code


def run_context_propose(args: argparse.Namespace) -> int:
    from ..ops.context_notes import op_context_propose
    from ..projects import resolve

    result = op_context_propose(resolve(args.project, args.config), write=args.write)
    print(result.summary)
    text = "\n".join(result.lines) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))
    return result.exit_code


def run_context_note(args: argparse.Namespace) -> int:
    from ..ops.context_notes import op_context_note
    from ..projects import resolve

    approved = dict(a.split("=", 1) for a in args.approve if "=" in a)
    if not args.note and not approved:
        print("context-note needs --note or --approve LOCALE=TEXT", file=sys.stderr)
        return 2
    result = op_context_note(resolve(args.project, args.config), key=args.key, note=args.note,
                             approved=approved or None)
    print(result.summary)
    for line in result.lines:
        print(line)
    return result.exit_code


def run_server_copy(args: argparse.Namespace) -> int:
    import json

    from ..ops.server_copy import op_server_copy
    from ..projects import resolve

    result = op_server_copy(resolve(args.project, args.config))
    if args.fmt == "json":
        print(json.dumps(result.data, ensure_ascii=False, indent=2))
        return result.exit_code
    text = "\n".join([result.summary, *result.lines]) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))
    return result.exit_code


def _print_result(result) -> int:
    text = "\n".join([result.summary, *result.lines]) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))
    return result.exit_code


def run_glossary_learn(args: argparse.Namespace) -> int:
    from ..ops.glossary_learn import op_glossary_learn
    from ..projects import resolve

    return _print_result(op_glossary_learn(resolve(args.project, args.config),
                                           locale=args.locale, write=args.write))


def run_import_review(args: argparse.Namespace) -> int:
    from ..ops.import_review import op_import_review
    from ..projects import resolve

    return _print_result(op_import_review(resolve(args.project, args.config), locale=args.locale,
                                          path=args.csv_path, dry_run=args.dry_run))
