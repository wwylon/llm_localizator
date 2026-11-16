"""Shared helpers for ops dispatch (B3)."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from contextvars import ContextVar

from ..projects import ProjectConfig
from ..projects.collections import get_collection
from .command_descriptor import read_only_ops
from .types import parse_csv_list, resolve_namespaces

_log = logging.getLogger("llm_localizator.ops.dispatch")

Reporter = Callable[[str], None]

# Optional Catalog from AppState when web dispatches (avoids rebuild).
_op_catalog: ContextVar[object | None] = ContextVar("llm_op_catalog", default=None)
_op_status_rows: ContextVar[object | None] = ContextVar("llm_op_status_rows", default=None)


def _ns_pair(body: dict) -> tuple[str | None, list[str] | None]:
    """(namespace, namespaces) from a request body; a lone list entry fills ``namespace``."""
    namespaces = resolve_namespaces(body.get("namespace"), body.get("namespaces"))
    namespace = body.get("namespace")
    if not namespace and namespaces and len(namespaces) == 1:
        namespace = namespaces[0]
    return namespace, namespaces


def _key_list(value) -> list[str] | None:
    return parse_csv_list(value)


def _float_or(value, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


class FieldError(ValueError):
    """A request field with the wrong type. ``dispatch_op`` turns it into an error result (HTTP 400), not a 500."""


def _int_or(body: dict, key: str, default: int) -> int:
    """An integer field: blank means the default, anything else must be a whole number (M0, audit ops #15)."""
    value = body.get(key)
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise FieldError(f"{key} must be a whole number")
    try:
        return int(str(value).strip())
    except ValueError:
        raise FieldError(f"{key} must be a whole number, not {value!r}") from None


def _num_or(body: dict, key: str, default: float | None) -> float | None:
    """A numeric field: blank means the default, anything else must be a number."""
    value = body.get(key)
    if value in (None, ""):
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        raise FieldError(f"{key} must be a number, not {value!r}") from None


# Ops that never write; they skip the stderr JSON log and the completion webhook.
_READ_ONLY_OPS = read_only_ops()

_FILE_COLLECTION_COMMANDS = frozenset({
    "status", "export", "translate", "documents",
})

def _path_body_keys() -> dict[str, tuple[str, ...]]:
    """Body keys that name a path, per command, from ``CommandDescriptor.path_keys`` (M3: was a second hand table).

    Each snake_case key also accepts its camelCase spelling (``out_dir`` / ``outDir``), as the web sends both.
    """
    from .command_descriptor import COMMANDS

    out: dict[str, tuple[str, ...]] = {}
    for desc in COMMANDS:
        if not desc.path_keys:
            continue
        keys: list[str] = []
        for key in desc.path_keys:
            keys.append(key)
            head, *rest = key.split("_")
            if rest:
                keys.append(head + "".join(part.title() for part in rest))
        out[desc.name.replace("-", "_")] = tuple(keys)
    return out


_PATH_BODY_KEYS = _path_body_keys()


def _emit_op_json_log(
    *,
    command: str,
    body: dict,
    exit_code: int,
    wall_seconds: float,
) -> None:
    """One JSON object on stderr per finished op (W-12 / F.4)."""
    locales = body.get("locales")
    if locales is None:
        locale_field: str | list[str] = body.get("locale") or ""
    elif isinstance(locales, str):
        locale_field = [p.strip() for p in locales.split(",") if p.strip()]
    else:
        locale_field = [str(x) for x in locales]

    keys = body.get("keys")
    if keys is None:
        keys_field: int | list[str] = 0
    elif isinstance(keys, str):
        parts = [p.strip() for p in keys.split(",") if p.strip()]
        keys_field = len(parts)
    elif isinstance(keys, (list, tuple)):
        keys_field = len(keys)
    else:
        try:
            keys_field = int(keys)
        except (TypeError, ValueError):
            keys_field = 0

    payload = {
        "command": command.replace("_", "-"),
        "locale": locale_field,
        "keys": keys_field,
        "wall_seconds": round(float(wall_seconds), 3),
        "exit": int(exit_code),
    }
    line = json.dumps(payload, ensure_ascii=False)
    print(line, file=sys.stderr, flush=True)
    _log.debug("op_log %s", line)


def _file_collection_block(cfg: ProjectConfig, command: str, body: dict) -> dict | None:
    """Key-catalogue commands do not silently run when a file collection is selected."""
    name = str(body.get("collection") or "messages").strip() or "messages"
    if name == "messages" or command in _FILE_COLLECTION_COMMANDS:
        return None
    try:
        coll = get_collection(cfg, name)
    except ValueError as exc:
        return {"ok": False, "exit_code": 64, "summary": str(exc), "error": str(exc)}
    if coll.kind == "messages":
        return None
    summary = (
        f"{name} is a file collection. Status, export, and translate apply to it. "
        "This command stays on the message catalogue."
    )
    return {
        "ok": False,
        "exit_code": 64,
        "command": command.replace("_", "-"),
        "summary": summary,
        "lines": [summary],
    }


def _escaping_path(cfg, command: str, body: dict, role: str | None) -> str:
    """A request-supplied path outside the project root, for non-Admin roles.

    Admin (and trusted in-process callers) may name any path; everyone else
    is confined to the project so a Translator cannot write TMX anywhere.
    """
    from .permissions import ROLE_ADMIN

    keys = _PATH_BODY_KEYS.get(command)
    if not keys or cfg is None or role == ROLE_ADMIN:
        return ""
    from pathlib import Path

    from ..projects.paths import is_under_root

    exports = export_dir(cfg) if command in _EXPORT_WRITE_COMMANDS else None
    for key in keys:
        raw = body.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            path = cfg.root / path
        if command in _EXPORT_WRITE_COMMANDS:
            # A file the caller names and the op overwrites: inside the repo that could be the config or source,
            # so non-Admins may only write under the engine's exports folder.
            if not is_under_root(path, exports):
                return f"{raw} (non-Admin exports go under {exports})"
        elif not is_under_root(path, cfg.root):
            return str(raw)
    return ""


#: Ops that overwrite a file named in the request (M0, audit ops #4).
_EXPORT_WRITE_COMMANDS = frozenset({"tm_export", "glossary_export", "glossary_propose"})


def export_dir(cfg):
    """Where non-Admin exports may be written: ``<data root>/exports``."""
    return cfg.data_root() / "exports"
