"""CLI command manifest for web UI form generation."""

from __future__ import annotations

import argparse
from typing import Any

from .command_descriptor import submit_ops
from .permissions import DEFAULT_MATRIX, ROLE_ADMIN, ROLES


def _action_fields(action: argparse.Action) -> dict[str, Any]:
    opts = list(action.option_strings)
    name = action.dest
    if name in ("help", "version", "command"):
        return {}
    field: dict[str, Any] = {
        "name": name,
        "flags": opts,
        "required": bool(getattr(action, "required", False)),
    }
    if action.choices:
        field["choices"] = list(action.choices)
    if action.default is not None and action.default != argparse.SUPPRESS:
        if not callable(action.default):
            field["default"] = action.default
    if isinstance(action, argparse._StoreTrueAction):
        field["type"] = "bool"
    elif isinstance(action, argparse._StoreFalseAction):
        field["type"] = "bool"
    elif action.type is not None:
        field["type"] = getattr(action.type, "__name__", str(action.type))
    else:
        field["type"] = "str"
    if action.help:
        field["help"] = action.help.split(".")[0]
    return field


# One list. The operations page reads ``group``; it does not keep its own names.
_GROUPS = {
    "Analysis": (
        "validate", "status", "scan", "discover", "estimate-cost",
        "agent-backlog", "agent-hardcoded", "scan-decide", "patch", "apply",
        "ingest-visual", "adopt", "sync",
        "term-report", "release-diff",
    ),
    "LLM Pipeline": ("translate", "improve", "review", "rescore", "documents", "bakeoff"),
    "Data": ("export", "import", "migrate-state", "release-freeze"),
    "Maintenance": ("guide", "doctor", "init"),
}
_GROUP_OF = {name: group for group, names in _GROUPS.items() for name in names}
_GROUP_NAMES = list(_GROUPS.keys()) + ["Other"]
# Queue + inline LLM ops (run-* live in Other but still need a model).
_REQUIRES_LLM = frozenset(_GROUPS["LLM Pipeline"]) | frozenset(
    f"run-{name}" for name in _GROUPS["LLM Pipeline"]
)

# ``--submit`` is not a CLI flag. These dispatch bodies read ``body["submit"]``.
_SUBMIT = submit_ops()


def _roles_for(name: str) -> list[str]:
    flags = DEFAULT_MATRIX.get(name)
    if flags is None:
        return [ROLE_ADMIN]
    return [role for role, allowed in zip(ROLES, flags) if allowed]


def _help_by_name(sub_action: argparse._SubParsersAction) -> dict[str, str]:
    out: dict[str, str] = {}
    for action in getattr(sub_action, "_choices_actions", []) or []:
        dest = getattr(action, "dest", None)
        if dest:
            out[str(dest)] = (action.help or "").strip()
    return out


# CLI / HTTP ops that are not driven from the Operations carousel.
_OPS_EXCLUDED = frozenset({"web", "mcp", "add-locale", "watch", "check", "workflow", "quality",
                           "runtime", "check-keys", "approach",
                           "help", "skill", "set", "review-risk", "cycle", "onboard",
                           "context-propose", "context-note", "server-copy",
                           "glossary-learn", "import-review"})  # CLI-only: ADR-118, ADR-123


def build_commands_manifest(parser: argparse.ArgumentParser) -> dict:
    """Introspect the CLI parser built by ``cli.main.build_parser``."""
    from .dispatch import is_streamable

    commands: dict[str, Any] = {}
    sub_action = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)),
        None,
    )
    if sub_action is None:
        return {
            "commands": commands,
            "groups": list(_GROUP_NAMES),
            "group_order": {g: list(n) for g, n in _GROUPS.items()},
        }
    helps = _help_by_name(sub_action)
    for name, sub in sub_action.choices.items():
        if name in _OPS_EXCLUDED:
            continue
        fields = []
        for action in sub._actions:
            if isinstance(action, argparse._SubParsersAction):
                continue
            f = _action_fields(action)
            if f:
                fields.append(f)
        dests = {f["name"] for f in fields}
        group = _GROUP_OF.get(name, "Other")
        entry: dict[str, Any] = {
            "fields": fields,
            "group": group,
            "submit": name in _SUBMIT or "submit" in dests or "submit_translate" in dests,
            "stream": is_streamable(name),
            "description": helps.get(name) or (getattr(sub, "description", None) or ""),
            # Top-level flag for the UI badge — not the argparse ``--llm`` field.
            "requires_llm": name in _REQUIRES_LLM,
            "llm": name in _REQUIRES_LLM,
            "roles": _roles_for(name),
        }
        if name == "export":
            entry["kind"] = "file-export"
        elif name == "import":
            entry["kind"] = "file-import"
        commands[name] = entry
    return {
        "commands": commands,
        "groups": list(_GROUP_NAMES),
        "group_order": {g: list(n) for g, n in _GROUPS.items()},
    }
