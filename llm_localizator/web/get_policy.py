"""GET route policy table (parallel to post_policy). ADR deep-health Wave 0/2.

Every private catalogue GET must declare a policy. ``anonymous`` is for
overlay/translator-bundle routes that intentionally stay public on loopback.
"""

from __future__ import annotations

from typing import Literal

Policy = Literal["auth", "admin", "anonymous"]

__all__ = ["GET_POLICY", "policy_for_get"]

# Exact paths only (same shape as server._GET_ROUTES keys).
GET_POLICY: dict[str, Policy] = {
    "/api/projects": "auth",
    "/api/ui-locales": "anonymous",
    "/api/dashboard": "auth",
    "/api/overview": "auth",
    "/api/overview-lite": "auth",
    "/api/overview-stats": "auth",
    "/api/collections": "auth",
    "/api/collection-files": "auth",
    "/api/collection-file": "auth",
    "/api/models": "auth",
    "/api/locales": "auth",
    "/api/setup-state": "auth",
    "/api/messages": "auth",
    "/api/messages/row": "auth",
    "/api/findings": "auth",
    "/api/export": "auth",
    "/api/screenshot": "auth",
    "/api/commands": "auth",
    "/api/version": "anonymous",
    "/api/bootstrap-token": "anonymous",
    "/api/history": "auth",
    "/overlay.js": "anonymous",
    "/overlay.css": "anonymous",
    "/api/tm/concordance": "auth",
    "/api/tm/leverage": "auth",
    "/api/tm/browse": "auth",
    "/api/tm/export": "auth",
    "/api/report-parts": "auth",
    "/api/report-part": "auth",
    "/api/glossary": "auth",
    "/api/bundle": "anonymous",
    "/api/auth/me": "anonymous",
    "/api/settings": "auth",
    "/api/provider-status": "auth",
    "/api/project-config": "auth",
    "/api/model-eval": "auth",
    "/api/workflow": "auth",
    "/api/workflow/run": "auth",
    "/api/workflow/summary": "auth",
    "/api/branches": "auth",
    "/api/branches/sync": "auth",
    "/api/branches/merge-preview": "auth",
    "/api/branches/diff": "auth",
    "/api/usage": "auth",
    "/api/usage/export": "auth",
    "/api/progress": "auth",
    "/api/translator-activity": "auth",
    "/api/metrics": "auth",
    "/api/status": "auth",
    "/api/scan/status": "auth",
    "/api/queue": "auth",
    "/api/scan/hits": "auth",
    "/api/analysis": "auth",
    "/api/analysis/report": "auth",
    "/api/review/tickets": "auth",
    "/api/review/counts": "auth",
    "/api/translator-lookup": "anonymous",
    "/api/translator-bundle": "anonymous",
    "/api/translator-config": "anonymous",
}


def policy_for_get(path: str) -> Policy | None:
    return GET_POLICY.get(path)
