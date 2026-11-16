"""stdio MCP server for agents. Optional extra: ``pip install llm_localizator[mcp]``."""

from __future__ import annotations

import json


def main() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "error: MCP extra is not installed. "
            "Install with: pip install 'llm_localizator[mcp]'",
        )
        return 1

    from ..projects import resolve
    from ..projects.config import ConfigError
    from ..ops.agent_mcp import dispatch_mcp_tool

    mcp = FastMCP("llm-localizator")

    def _run(name: str, project: str, **arguments) -> str:
        try:
            cfg = resolve(project)
        except ConfigError as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        payload = dispatch_mcp_tool(cfg, name, arguments)
        return json.dumps(payload, ensure_ascii=False)

    @mcp.tool()
    def estimate_localization_cost(
        project: str,
        locales: str = "",
        namespaces: str = "",
        keys: str = "",
    ) -> str:
        """Maximum USD to localize due strings. Does not call a model or spend."""
        return _run(
            "estimate_localization_cost", project,
            locales=locales, namespaces=namespaces, keys=keys,
        )

    @mcp.tool()
    def request_localization(project: str, keys: str, locales: str = "") -> str:
        """Localize an explicit key list. Requires budget mode on_request."""
        return _run("request_localization", project, keys=keys, locales=locales)

    @mcp.tool()
    def localize_due(project: str, locales: str = "") -> str:
        """Localize strings that are due. Requires budget mode dynamic."""
        return _run("localize_due", project, locales=locales)

    @mcp.tool()
    def localization_status(project: str, missing: bool = False) -> str:
        """Coverage and leverage summary. Does not call a model."""
        return _run("localization_status", project, missing=missing)

    @mcp.tool()
    def validate_catalogue(
        project: str,
        locales: str = "",
        namespaces: str = "",
    ) -> str:
        """Run catalogue validation without writing flags."""
        return _run(
            "validate_catalogue", project,
            locales=locales, namespaces=namespaces,
        )

    @mcp.tool()
    def source_impact(project: str) -> str:
        """Keys whose stored src_sha no longer matches source. Read-only."""
        return _run("source_impact", project)

    @mcp.tool()
    def agent_backlog(
        project: str,
        locales: str = "",
        namespaces: str = "",
        split: str = "",
        out_dir: str = "",
        budget_tokens: int = 0,
    ) -> str:
        """Agent-ready backlog of missing / stale / empty keys.

        With split=locale|namespace it writes size-bounded part files under out_dir
        (inside the project) and returns the part index; otherwise it writes nothing.
        """
        return _run(
            "agent_backlog", project,
            locales=locales, namespaces=namespaces,
            split=split, out_dir=out_dir, budget_tokens=budget_tokens,
        )

    @mcp.tool()
    def list_places(project: str) -> str:
        """Text places (catalogue namespaces) and their policy: auto, request, review, never. Read-only."""
        return _run("list_places", project)

    @mcp.tool()
    def check_keys(project: str, strict: bool = False) -> str:
        """Keys used in source vs the source catalogue, unused keys, stale en-XX. No LLM, read-only."""
        return _run("check_keys", project, strict=strict)

    @mcp.tool()
    def hardcoded_status(project: str) -> str:
        """Scan cache and en-XX readiness plus the next hardcoded-text steps. Read-only."""
        return _run("hardcoded_status", project)

    @mcp.tool()
    def list_approaches(project: str) -> str:
        """How this project can be localized (local, cloud, agent, human, hybrid) and a recommendation.

        Show these to the user and let them choose before translating (agent guide rule 2).
        """
        return _run("list_approaches", project)

    from ..help import guide_text

    @mcp.resource("llm-localizator://help/agent")
    def help_agent() -> str:
        """Rules and recipes for AI agents working with llm-localizator. Read first."""
        return guide_text("agent")

    @mcp.resource("llm-localizator://help/human")
    def help_human() -> str:
        """The operator's guide: decisions, workflow, reading results."""
        return guide_text("human")

    mcp.run()
    return 0
