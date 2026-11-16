"""Agent MCP tool handlers. No MCP SDK import — the server only adapts these."""

from __future__ import annotations

from ..projects import ProjectConfig
from ..projects.paths import is_under_root
from .agent_backlog import op_agent_backlog
from .estimate_cost import op_estimate_cost
from .places import op_places
from .source_ops import op_impact
from .status import op_status
from .translate import op_translate
from .types import (
    AgentBacklogRequest,
    EstimateCostRequest,
    OpResult,
    StatusRequest,
    TranslateRequest,
    ValidateRequest,
    parse_csv_list,
)
from .validate import op_validate

__all__ = [
    "MCP_TOOLS",
    "estimate_localization_cost",
    "request_localization",
    "localize_due",
    "localization_status",
    "validate_catalogue",
    "source_impact",
    "agent_backlog",
    "list_places",
    "dispatch_mcp_tool",
]
# check_keys, hardcoded_status and list_approaches (ADR-121, ADR-123) are dispatched below.

# Documented list for W-09 phase notes / tests (E.1).
MCP_TOOLS = (
    "estimate_localization_cost",
    "request_localization",
    "localize_due",
    "localization_status",
    "validate_catalogue",
    "source_impact",
    "agent_backlog",
    "list_places",
    "check_keys",
    "hardcoded_status",
    "list_approaches",
)


def estimate_localization_cost(
    cfg: ProjectConfig,
    *,
    locales: list[str] | None = None,
    namespaces: list[str] | None = None,
    keys: list[str] | None = None,
) -> OpResult:
    return op_estimate_cost(cfg, EstimateCostRequest(
        locales=locales, namespaces=namespaces, keys=keys,
    ))


def request_localization(
    cfg: ProjectConfig,
    *,
    keys: list[str] | None,
    locales: list[str] | None = None,
) -> OpResult:
    """Spend only in ``on_request`` mode, and only for ``keys``."""
    if (getattr(cfg, "budget_mode", "on_request") or "on_request") != "on_request":
        summary = 'request_localization requires [budget] mode = "on_request"'
        return OpResult(ok=False, exit_code=1, command="translate", summary=summary, lines=[summary])
    if not keys:
        summary = "request_localization requires keys"
        return OpResult(ok=False, exit_code=1, command="translate", summary=summary, lines=[summary])
    quote = op_estimate_cost(cfg, EstimateCostRequest(locales=locales, keys=keys))
    if not quote.ok:
        return quote
    if not quote.data.get("local") and not quote.data.get("allowed", False):
        return OpResult(
            ok=False, exit_code=1, command="translate",
            summary=quote.summary, lines=quote.lines, data=quote.data,
        )
    result = op_translate(cfg, TranslateRequest(
        locales=locales, keys=list(keys), submit=True,
    ))
    result.data = {**quote.data, **result.data}
    if quote.summary and quote.summary not in result.lines:
        result.lines = [quote.summary, *result.lines]
    return result


def localize_due(
    cfg: ProjectConfig,
    *,
    locales: list[str] | None = None,
) -> OpResult:
    """Enqueue the due set. Only when mode is ``dynamic``."""
    if (getattr(cfg, "budget_mode", "on_request") or "on_request") != "dynamic":
        summary = 'localize_due requires [budget] mode = "dynamic"'
        return OpResult(ok=False, exit_code=1, command="translate", summary=summary, lines=[summary])
    quote = op_estimate_cost(cfg, EstimateCostRequest(locales=locales))
    if not quote.ok:
        return quote
    if not quote.data.get("local") and not quote.data.get("allowed", False):
        return OpResult(
            ok=False, exit_code=1, command="translate",
            summary=quote.summary, lines=quote.lines, data=quote.data,
        )
    result = op_translate(cfg, TranslateRequest(locales=locales, submit=True))
    result.data = {**quote.data, **result.data}
    if quote.summary and quote.summary not in result.lines:
        result.lines = [quote.summary, *result.lines]
    return result


def localization_status(cfg: ProjectConfig, *, missing: bool = False) -> OpResult:
    return op_status(cfg, StatusRequest(missing=missing))


def validate_catalogue(
    cfg: ProjectConfig,
    *,
    locales: list[str] | None = None,
    namespaces: list[str] | None = None,
) -> OpResult:
    namespace = None
    if namespaces and len(namespaces) == 1:
        namespace = namespaces[0]
    return op_validate(cfg, ValidateRequest(
        locales=locales,
        namespace=namespace,
        namespaces=namespaces,
        write_flags=False,
    ))


def source_impact(cfg: ProjectConfig) -> OpResult:
    return op_impact(cfg)


def agent_backlog(
    cfg: ProjectConfig,
    *,
    locales: list[str] | None = None,
    namespaces: list[str] | None = None,
    split: str | None = None,
    out_dir: str | None = None,
    budget_tokens: int | None = None,
) -> OpResult:
    """With ``split`` the parts are written under the project root (never elsewhere)."""
    fixed_dir = None
    if out_dir:
        target = (cfg.root / out_dir).resolve()
        if not is_under_root(target, cfg.root):
            summary = "out_dir must stay inside the project"
            return OpResult(ok=False, exit_code=1, command="agent-backlog", summary=summary, lines=[summary])
        fixed_dir = str(target)
    if split not in (None, "", "locale", "namespace"):
        summary = "split must be locale or namespace"
        return OpResult(ok=False, exit_code=1, command="agent-backlog", summary=summary, lines=[summary])
    return op_agent_backlog(cfg, AgentBacklogRequest(
        locales=locales,
        namespaces=namespaces,
        fmt="json",
        split=split or None,
        out_dir=fixed_dir,
        budget_tokens=budget_tokens or 15000,
    ))


def list_places(cfg: ProjectConfig) -> OpResult:
    """Read-only. Changing a place policy stays a CLI / web action (it edits config)."""
    return op_places(cfg, "list")


def dispatch_mcp_tool(cfg: ProjectConfig, name: str, arguments: dict) -> dict:
    """Run one tool. ``arguments`` never carry an API key."""
    for forbidden in ("api_key", "token", "authorization"):
        if forbidden in arguments:
            return {"ok": False, "error": "API keys are not accepted as tool arguments"}
    locales = _csv(arguments.get("locales"))
    namespaces = _csv(arguments.get("namespaces"))
    keys = _csv(arguments.get("keys"))
    if name == "estimate_localization_cost":
        return estimate_localization_cost(
            cfg, locales=locales, namespaces=namespaces, keys=keys,
        ).to_dict()
    if name == "request_localization":
        return request_localization(cfg, keys=keys, locales=locales).to_dict()
    if name == "localize_due":
        return localize_due(cfg, locales=locales).to_dict()
    if name == "localization_status":
        return localization_status(cfg, missing=bool(arguments.get("missing"))).to_dict()
    if name == "validate_catalogue":
        return validate_catalogue(cfg, locales=locales, namespaces=namespaces).to_dict()
    if name == "source_impact":
        return source_impact(cfg).to_dict()
    if name == "agent_backlog":
        try:
            budget = int(arguments.get("budget_tokens") or 0) or None
        except (TypeError, ValueError):
            return {"ok": False, "error": "budget_tokens must be an integer"}
        return agent_backlog(
            cfg, locales=locales, namespaces=namespaces,
            split=str(arguments.get("split") or "") or None,
            out_dir=str(arguments.get("out_dir") or "") or None,
            budget_tokens=budget,
        ).to_dict()
    if name == "list_places":
        return list_places(cfg).to_dict()
    if name == "check_keys":
        from .web_runtime import op_check_keys

        return op_check_keys(cfg, strict=bool(arguments.get("strict"))).to_dict()
    if name == "hardcoded_status":
        from .agent_hardcoded import scan_cache_status

        return {"ok": True, "command": "hardcoded_status", "data": scan_cache_status(cfg)}
    if name == "list_approaches":
        from .approaches import op_approach

        return op_approach(cfg).to_dict()
    return {"ok": False, "error": f"unknown tool {name!r}"}


def _csv(value) -> list[str] | None:
    return parse_csv_list(value)
