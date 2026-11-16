"""One authorisation table for every POST route (plan-review-7 phase 1, ADR-58).

Policies
--------
``admin``   config / identity: needs an approved Admin (or the startup token).
``edit``    catalogue writes: needs an approved actor; every locale named in
            the body must pass ``locale_allowed``. ``POST_OPS`` adds a role
            check through the ADR-39 matrix.
``read``    read-only work done over POST (export, preview, resolve): needs an
            approved actor and the same locale scope, but no write role.
``inline``  handled in ``do_POST`` before the generic gate (auth flows and
            ``/api/setup``); each does its own actor check.

``/api/ops/*`` and ``/api/review/tickets/*`` are prefix routes (see
``PREFIX_POLICY``). A test fails when a route in ``_Handler._POST_ROUTES`` or an
inline ``url.path ==`` branch is missing here.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "POST_OPS", "POST_POLICY", "PREFIX_POLICY", "body_locales", "policy_for",
]

POST_POLICY: dict[str, str] = {
    # inline routes
    "/api/auth/register": "inline",
    "/api/auth/login": "inline",
    "/api/auth/logout": "inline",
    "/api/auth/users": "inline",
    "/api/auth/users/approve": "inline",
    "/api/auth/users/deny": "inline",
    "/api/auth/users/remove": "inline",
    "/api/setup": "inline",
    "/api/setup/smoke-test": "inline",
    # config / identity
    "/api/settings": "admin",
    "/api/project-config": "admin",
    "/api/web-token": "admin",
    "/api/add-locale": "admin",
    "/api/remove-locale": "admin",
    "/api/translate-enabled": "admin",
    "/api/reload": "admin",
    "/api/model-eval/run": "admin",
    "/api/model-eval/apply": "admin",
    # catalogue writes
    "/api/save": "edit",
    "/api/flag": "edit",
    "/api/verify": "edit",
    "/api/revert": "edit",
    "/api/validate-key": "edit",
    "/api/context": "edit",
    "/api/screenshot-upload": "edit",
    "/api/mark-example": "edit",
    "/api/mark-intentional": "edit",
    "/api/lock": "edit",
    "/api/retranslate": "edit",
    "/api/collection-file": "edit",
    "/api/glossary": "edit",
    "/api/import": "edit",
    "/api/push-strings": "edit",
    "/api/tm/import": "edit",
    "/api/workflow": "edit",
    "/api/workflow/cancel": "edit",
    "/api/workflow/resume": "edit",
    "/api/workflow/copy": "edit",
    "/api/save-ui-locale": "edit",
    "/api/review/tickets": "edit",
    "/api/branches/track": "edit",
    "/api/branches/active": "edit",
    "/api/branches/merge": "edit",
    "/api/branches/archive": "edit",
    "/api/branches/unarchive": "edit",
    "/api/branches/delete": "edit",
    "/api/branches/fetch": "edit",
    # read-only over POST
    "/api/export": "read",
    "/api/preview": "read",
    "/api/resolve": "read",
}

# Extra ADR-39 matrix check for edit routes that map to an operation.
POST_OPS: dict[str, str] = {
    "/api/retranslate": "translate",
    "/api/import": "import",
    "/api/push-strings": "push-strings",
    "/api/workflow": "workflow",
    "/api/workflow/copy": "workflow",
    "/api/workflow/cancel": "workflow",
    "/api/workflow/resume": "workflow",
    "/api/export": "export",
}

# Prefix routes: (prefix, policy). The op role check for /api/ops/ stays in do_POST.
PREFIX_POLICY: tuple[tuple[str, str], ...] = (
    ("/api/ops/", "edit"),
    ("/api/review/tickets/", "edit"),
)


def policy_for(path: str) -> str | None:
    found = POST_POLICY.get(path)
    if found is not None:
        return found
    for prefix, policy in PREFIX_POLICY:
        if path.startswith(prefix):
            return policy
    return None


def body_locales(body: dict[str, Any]) -> list[str]:
    """Every locale a request body names (``locale`` and ``locales``)."""
    out: list[str] = []
    one = body.get("locale")
    if one:
        out.append(str(one))
    many = body.get("locales")
    if isinstance(many, str):
        out.extend(p.strip() for p in many.split(",") if p.strip())
    elif isinstance(many, (list, tuple)):
        out.extend(str(x) for x in many if x)
    return out
