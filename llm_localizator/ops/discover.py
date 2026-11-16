"""``llm-localizator discover`` — propose text collections, write nothing."""

from __future__ import annotations

from ..projects import ProjectConfig
from ..projects.collections import discover_collections
from .types import OpResult

__all__ = ["op_discover"]


def op_discover(cfg: ProjectConfig) -> OpResult:
    proposals = discover_collections(cfg.root)
    lines = [
        "Discover only proposes. Copy a confirmed root into .llm-localize.toml.",
        "Omitting a collection keeps the current command meaning (messages).",
        "",
    ]
    if not proposals:
        lines.append("No locale-named directories found.")
    for item in proposals:
        loc = ", ".join(item["locales"])
        lines.append(
            f"{item['name']}: {item['format']} at `{item['root'] or '.'}` ({loc})"
        )
        for warning in item["warnings"]:
            lines.append(f"  warning: {warning}")
    claimed = str(getattr(cfg, "catalog_path", "") or "").replace("\\", "/")
    unclaimed = [p for p in proposals if not (p["root"] and claimed.startswith(p["root"].rstrip("/") + "/"))]
    snippet: list[str] = []
    for item in unclaimed:
        snippet += [f'[places."{item["name"]}"]', 'policy = "request"', ""]
    if snippet:
        lines += ["", "Unclaimed places (ADR-104). Paste to list them; `request` translates only on demand.",
                  "Adjust each pattern to your namespace names:", ""] + snippet
    return OpResult(
        ok=True,
        exit_code=0,
        command="discover",
        summary=f"{len(proposals)} collection(s) proposed",
        lines=lines,
        data={"proposals": proposals, "places_snippet": "\n".join(snippet).rstrip()},
    )
