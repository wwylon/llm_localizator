"""Every option the Ops drawer shows is either passed on by the web handler or ignored on purpose (plan D1).

The drawer builds its forms from argparse (``ops/manifest.py``) and posts the argparse ``dest``
names as body keys. A handler in ``ops/dispatch_cmds.py`` that never reads one of those keys
shows the user an option that does nothing (``agent-hardcoded --show-low`` did that until
2026-11-11). Reading a key means the handler, or an ops helper it calls, mentions it as a
quoted string.
"""

from __future__ import annotations

import inspect
import re

from llm_localizator.cli.main import build_parser
from llm_localizator.ops import build_commands_manifest, dispatch, dispatch_cmds

#: Options no handler reads, on every command.
_GLOBAL_IGNORED = {
    "project": "the web picks the project from the session",
    "engine": "read once in dispatch_op, which reloads the config with that engine (ADR-156)",
    "config": "the web picks the project from the session",
    "branch": "the web sets the active branch on the Branches page",
    "fmt": "output style for the terminal; the web renders the data itself",
    "quiet": "terminal output only",
    "verbose": "terminal output only",
}

#: (command, dest) -> why the web leaves it out. Add here only with a reason.
_WEB_IGNORED = {
    ("engine", "json"): "CLI output format; the web reads the result data",
    ("documents", "draft_edits"): "prints draft diffs to the terminal and writes nothing",
    ("run-documents", "draft_edits"): "prints draft diffs to the terminal and writes nothing",
    ("export", "out"): "a server-side path; the web downloads the file instead",
    ("export", "report"): "a server-side report path; the web shows the result inline",
    ("import", "file"): "server-side paths; the web uploads the file content (csv / xliff / json / xlsx_base64)",
    ("hardcoded-hunt", "serve"): "the web never starts the consumer app",
    ("import", "report"): "writes a report file next to the CLI; the web shows the result inline",
    ("translate", "manifest"): "the CLI reads the manifest file into keys; the web sends keys",
    ("run-translate", "manifest"): "the CLI reads the manifest file into keys; the web sends keys",
    ("translate", "keys_file"): "the CLI reads the file into keys; the web sends keys",
    ("run-translate", "keys_file"): "the CLI reads the file into keys; the web sends keys",
    ("translate", "ignore_min_keys"): "worker-side guard override, set per queued task",
    ("run-translate", "ignore_min_keys"): "worker-side guard override, set per queued task",
    ("term-report", "json"): "terminal output style",
    ("doctor", "json"): "terminal output style",
    ("guide", "json"): "terminal output style",
    ("guide", "smoke_test"): "calls a model; the web guide stays read-only",
    ("guide", "yes"): "answers terminal prompts; the web guide asks nothing",
    ("guide", "no_input"): "answers terminal prompts; the web guide asks nothing",
    ("init", "yes"): "answers terminal prompts; the web setup has its own confirm",
    ("init", "approach"): "not wired yet: plan D4 adds approach to the setup wizard",
}

#: Handled inline in ``dispatch._dispatch_op_body`` rather than in ``_REGISTRY``.
_INLINE = {"init", "guide", "doctor"}


#: Small helpers that read body keys for a handler. ``op_*`` bodies are left out on purpose:
#: they quote output keys such as "by" or "status", which would hide a dropped option.
_BODY_HELPERS = {"_ns_pair", "_key_list", "_float_or", "parse_csv_list", "resolve_namespaces"}


def _ops_helpers() -> dict[str, str]:
    return {name: inspect.getsource(getattr(dispatch_cmds, name)) for name in _BODY_HELPERS
            if inspect.isfunction(getattr(dispatch_cmds, name, None))}


def _handler_source(command: str, helpers: dict[str, str]) -> str:
    key = command.replace("-", "_")
    if key.startswith("run_"):
        key = key[4:]
    if command in _INLINE:
        src = inspect.getsource(dispatch._dispatch_op_body)
    else:
        src = inspect.getsource(dispatch_cmds._REGISTRY[key])
    for name, helper in helpers.items():
        if re.search(rf"\b{re.escape(name)}\(", src):
            src += helper
    # ``request_from_mapping(SomeRequest, body)`` reads every field of that request (M3).
    from dataclasses import fields

    from llm_localizator.ops import types as op_types

    for cls_name in re.findall(r"request_from_mapping\(\s*(\w+)", src):
        cls = getattr(op_types, cls_name, None)
        if cls is not None:
            src += " ".join(f'"{f.name}"' for f in fields(cls))
    return src


def test_every_drawer_option_is_read_or_ignored_on_purpose() -> None:
    commands = build_commands_manifest(build_parser())["commands"]
    helpers = _ops_helpers()
    dropped = []
    for command, entry in sorted(commands.items()):
        src = _handler_source(command, helpers)
        for field in entry["fields"]:
            dest = field["name"]
            if dest in _GLOBAL_IGNORED or (command, dest) in _WEB_IGNORED:
                continue
            if f'"{dest}"' not in src and f"'{dest}'" not in src:
                dropped.append(f"{command} --{dest.replace('_', '-')}")
    assert not dropped, (
        "the web form shows these options but the handler ignores them; pass them on, "
        "or add them to _WEB_IGNORED with a reason: " + ", ".join(dropped)
    )


def test_ignore_list_has_no_stale_entries() -> None:
    commands = build_commands_manifest(build_parser())["commands"]
    stale = [pair for pair in _WEB_IGNORED
             if pair[0] not in commands or pair[1] not in {f["name"] for f in commands[pair[0]]["fields"]}]
    assert not stale, f"no such option any more: {stale}"


def test_dropped_options_now_reach_the_requests(monkeypatch, tmp_path) -> None:
    """The four options the survey found dropped (plan D1) arrive in the request objects."""
    seen = {}
    monkeypatch.setattr(dispatch_cmds, "op_agent_hardcoded",
                        lambda cfg, req: seen.setdefault("ah", req) and _Result())
    monkeypatch.setattr(dispatch_cmds, "op_bakeoff",
                        lambda cfg, req, report=None: seen.setdefault("bo", req) and _Result())
    monkeypatch.setattr(dispatch_cmds, "op_metrics",
                        lambda cfg, req, catalog=None: seen.setdefault("me", req) and _Result())
    monkeypatch.setattr(dispatch_cmds, "op_export",
                        lambda cfg, req: seen.setdefault("ex", req) and _Result())
    dispatch_cmds._REGISTRY["agent_hardcoded"](None, {"show_low": True}, None)
    dispatch_cmds._REGISTRY["bakeoff"](None, {"propose_config": True}, None)
    dispatch_cmds._REGISTRY["metrics"](None, {"by": "locale"}, None)
    dispatch_cmds._REGISTRY["export"](None, {"approved_only": True}, None)
    assert seen["ah"].show_low is True
    assert seen["bo"].propose_config is True
    assert seen["me"].by == "locale"
    assert seen["ex"].approved_only is True


def test_open_pr_reads_the_form_dests(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(dispatch_cmds, "op_open_pr", lambda cfg, req: seen.setdefault("pr", req) and _Result())
    dispatch_cmds._REGISTRY["open_pr"](None, {"action": "open", "pr_branch": "l10n/pl", "yes": True}, None)
    assert seen["pr"].branch == "l10n/pl" and seen["pr"].confirm is True


class _Result:
    def to_dict(self) -> dict:
        return {"ok": True}
