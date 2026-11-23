"""Dispatch web/CLI operation requests."""

from __future__ import annotations

import time

from ..projects import ProjectConfig
from .init import op_init
from .types import GuideRequest, InitRequest
from .dispatch_cmds import STREAMABLE, _REGISTRY
from .dispatch_util import (
    Reporter,
    _READ_ONLY_OPS,
    _emit_op_json_log,
    _escaping_path,
    _file_collection_block,
    _key_list,
    _op_catalog,
    _op_status_rows,
)

# Re-exports for tests / callers that imported from dispatch.

# estimate_cost prices the run the form is about to start, so it honours the same one-run engine (W4): a local
# project with a cloud engine picked for one run must still get the cost prompt.
_ENGINE_OPS = frozenset({"translate", "improve", "review", "rescore", "documents", "estimate_cost"})


def dispatch_op(
    cfg: ProjectConfig | None,
    command: str,
    body: dict,
    *,
    report: Reporter | None = None,
    actor_role: str | None = None,
    actor_name: str | None = None,
    catalog=None,
    status_rows=None,
) -> dict:
    """Run one operation; return ``OpResult`` as dict.

    When ``report`` is set, long-running ops forward progress lines to it
    (used by SSE streaming from the web UI).

    ``actor_role`` enforces ADR-39 permissions. ``None`` is anonymous and is
    denied; trusted in-process callers (CLI, tests) pass ``ROLE_ADMIN``.

    ``catalog`` / ``status_rows`` are optional AppState caches from the web UI.
    """
    from .permissions import deny_message, role_allowed

    tok_c = _op_catalog.set(catalog)
    tok_r = _op_status_rows.set(status_rows)
    try:
        return _dispatch_op_inner(
            cfg, command, body,
            report=report, actor_role=actor_role, actor_name=actor_name,
        )
    finally:
        _op_catalog.reset(tok_c)
        _op_status_rows.reset(tok_r)


def _dispatch_op_inner(
    cfg: ProjectConfig | None,
    command: str,
    body: dict,
    *,
    report: Reporter | None = None,
    actor_role: str | None = None,
    actor_name: str | None = None,
) -> dict:
    from .permissions import deny_message, role_allowed

    command = command.replace("-", "_")
    op_name = command.replace("_", "-")
    # Map run_* aliases to the permission name.
    perm_name = op_name
    if perm_name.startswith("run-"):
        perm_name = perm_name[4:]
    role = actor_role
    mutating = command not in _READ_ONLY_OPS
    started = time.perf_counter()
    if not role_allowed(role, perm_name, cfg=cfg):
        msg = deny_message(role, perm_name)
        result = {"ok": False, "error": msg, "exit_code": 77, "summary": msg}
        if mutating:
            _emit_op_json_log(
                command=op_name,
                body=body,
                exit_code=77,
                wall_seconds=time.perf_counter() - started,
            )
        return result

    if command == "draft" and body.get("action") == "accept":
        from .permissions import task_scope_denied

        refs = list(body.get("keys") or []) if not isinstance(body.get("keys"), str) else [
            p.strip() for p in body["keys"].split(",") if p.strip()
        ]
        if body.get("namespace") and body.get("key"):
            refs.append(f"{body['namespace']}.{body['key']}")
        denied = task_scope_denied(cfg, role, actor_name, str(body.get("locale") or ""), refs)
        if denied:
            return {"ok": False, "error": denied, "exit_code": 77, "summary": denied}

    escaped = _escaping_path(cfg, command, body, role)
    if escaped:
        msg = f"path not allowed for this role: {escaped}"
        return {"ok": False, "error": msg, "exit_code": 77, "summary": msg}

    if body.get("engine") and command.removeprefix("run_") in _ENGINE_OPS and cfg is not None and cfg.config_path:
        # One-run engine from the web form (ADR-156): reload the config with it; queued submits pass it on.
        from ..projects.config import ConfigError, load_config

        try:
            cfg = load_config(cfg.config_path, engine_override=str(body["engine"]))
        except ConfigError as exc:
            return {"ok": False, "error": str(exc), "exit_code": 2, "summary": str(exc)}

    from .dispatch_util import FieldError

    try:
        result = _dispatch_op_body(cfg, command, body, report=report)
        exit_code = int(result.get("exit_code", 0 if result.get("ok", True) else 1))
    except FieldError as exc:
        return {"ok": False, "error": str(exc), "exit_code": 64, "summary": str(exc)}
    except Exception:
        if mutating:
            _emit_op_json_log(
                command=op_name,
                body=body,
                exit_code=1,
                wall_seconds=time.perf_counter() - started,
            )
        raise
    if cfg is not None and mutating and command not in {"init"}:
        from .notify import notify_project

        notify_project(
            cfg,
            {
                **({"event": "translate.done"} if op_name == "translate" else {}),
                "command": op_name,
                "ok": bool(result.get("ok", True)),
                "exit_code": result.get("exit_code", 0),
                "summary": result.get("summary") or result.get("error") or "",
                "project": cfg.name,
            })
    if mutating:
        _emit_op_json_log(
            command=op_name,
            body=body,
            exit_code=exit_code,
            wall_seconds=time.perf_counter() - started,
        )
    return result


def _dispatch_op_body(
    cfg: ProjectConfig | None,
    command: str,
    body: dict,
    *,
    report: Reporter | None = None,
) -> dict:
    """Inner dispatch after permission check."""
    # run-* CLI aliases execute in-process (never queue via submit flags).
    # Workers and the CLI are already a trusted confirm; do not re-prompt.
    if command.startswith("run_"):
        command = command[4:]
        body = dict(body)
        body["submit"] = False
        body["submit_translate"] = False
        body["inline"] = True
        body["confirm"] = True

    if command == "init":
        req = InitRequest(
            directory=body.get("directory"),
            name=body.get("name"),
            source_locale=body.get("source_locale", "en"),
            catalog_format=body.get("catalog_format") or body.get("format"),
            catalog_path=body.get("catalog_path") or body.get("path"),
            taskqueue=bool(body.get("taskqueue")),
            no_register=bool(body.get("no_register")),
            force=bool(body.get("force")),
            targets=_key_list(body.get("targets")),
            model=body.get("model") or None,
            domain=body.get("domain") or None,
            provider=body.get("provider") or None,
        )
        if not req.directory and cfg is not None:
            req.directory = str(cfg.root)
        return op_init(req).to_dict()

    if command == "guide":
        from .guide import op_guide

        # The smoke test calls a model, so it is CLI-only; the web path stays read-only.
        return op_guide(
            cfg,
            GuideRequest(
                directory=body.get("directory"),
                skip_provider=bool(body.get("skip_provider")),
                # Web polls guide on the dashboard; default skips full validate.
                skip_validate=bool(body["skip_validate"]) if "skip_validate" in body else True,
            ),
            catalog=_op_catalog.get(),
            status_rows=_op_status_rows.get(),
        ).to_dict()

    if command == "doctor":
        from ..doctor import run_doctor

        port = body.get("port", body.get("web_port", 8770))
        try:
            web_port = int(port) if port is not None else 8770
        except (TypeError, ValueError):
            web_port = 8770
        checks = run_doctor(
            cfg,
            web_port=web_port,
            skip_ollama=bool(body.get("skip_ollama")),
        )
        strict = bool(body.get("strict"))
        failed = [
            c for c in checks
            if c.status == "fail" or (strict and c.name == "ollama" and c.status == "warn")
        ]
        fails = bool(failed)
        lines = [f"{c.status}: {c.name}: {c.detail}" for c in checks]
        return {
            "ok": not fails,
            "exit_code": 1 if fails else 0,
            "command": "doctor",
            "summary": f"{len(checks)} check(s), {len(failed)} fail",
            "lines": lines,
            "data": {"checks": [c.to_dict() for c in checks]},
        }

    if cfg is None:
        return {"ok": False, "error": f"operation {command!r} requires a project"}

    blocked = _file_collection_block(cfg, command, body)
    if blocked is not None:
        return blocked

    handler = _REGISTRY.get(command)
    if handler is not None:
        return handler(cfg, body, report)
    return {"ok": False, "error": f"unknown operation {command!r}"}


def is_streamable(command: str) -> bool:
    return command.replace("-", "_") in STREAMABLE
