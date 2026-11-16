"""Role × operation matrix (SPEC §3 / ADR-39). Shared by CLI and web."""

from __future__ import annotations

from typing import Any

__all__ = [
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_SUPERVISOR",
    "ROLE_TRANSLATOR",
    "ROLE_DEVELOPER",
    "OPERATIONS",
    "DEFAULT_MATRIX",
    "role_allowed",
    "normalize_role",
    "deny_message",
    "task_scope_denied",
]

ROLE_ADMIN = "Admin"
ROLE_SUPERVISOR = "Supervisor"
ROLE_TRANSLATOR = "Translator"
ROLE_DEVELOPER = "Developer"
ROLES = (ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_TRANSLATOR, ROLE_DEVELOPER)

# Order matches shell Settings table and SPEC §3.
OPERATIONS = (
    "validate",
    "status",
    "estimate-cost",
    "scan",
    "discover",
    "verify",
    "projects",
    "places",
    "explain-skip",
    "agent-backlog",
    "agent-hardcoded",
    "hardcoded-hunt",
    "ingest-visual",
    "translate",
    "improve",
    "review",
    "rescore",
    "bakeoff",
    "documents",
    "export",
    "import",
    "migrate-state",
    "adopt",
    "sync",
    "doctor",
    "guide",
    "push-strings",
    "workflow",
    "term-report",
    "release-freeze",
    "release-diff",
    "suggest",
    "draft",
    "source-diff",
    "open-pr",
    "screenshot-link",
    "task",
    "discuss",
    "flag-source",
    "source-review-queue",
    "bulk-clear",
    "apply-near",
    "find-replace",
    "rename-placeholder",
    "scan-decide",
    "patch",
    "apply",
    "analytics",
    "metrics",
    "concordance",
    "tm-export",
    "tm-import",
    "org",
    "glossary-export",
    "glossary-import",
    "glossary-propose",
    "impact",
    "pseudo",
    "hard-keys",
    "explain-scan",
    "acknowledge-flush",
    "init",
    "engine",
    "queue-engine",
    "approach",
)

# role index: Admin, Supervisor, Translator, Developer
DEFAULT_MATRIX: dict[str, tuple[bool, bool, bool, bool]] = {
    "validate": (True, True, True, True),
    "status": (True, True, True, True),
    "estimate-cost": (True, True, False, True),
    "scan": (True, False, False, True),
    "discover": (True, False, False, True),
    "verify": (True, False, False, True),
    "projects": (True, False, False, True),
    "places": (True, False, False, True),
    "explain-skip": (True, True, True, True),
    "agent-backlog": (True, True, False, True),
    "agent-hardcoded": (True, False, False, True),
    "hardcoded-hunt": (True, False, False, True),
    "ingest-visual": (True, False, False, True),
    "translate": (True, True, False, False),
    "improve": (True, True, False, False),
    "review": (True, True, False, False),
    "rescore": (True, True, False, False),
    "bakeoff": (True, True, False, False),
    "documents": (True, True, False, False),
    "export": (True, True, True, True),
    "import": (True, True, False, True),
    "migrate-state": (True, False, False, False),
    "adopt": (True, False, False, False),
    "sync": (True, True, False, False),
    "doctor": (True, False, False, True),
    "guide": (True, True, True, True),
    "push-strings": (True, False, False, True),
    "workflow": (True, True, False, False),
    "term-report": (True, True, True, True),
    "release-freeze": (True, False, False, True),
    "release-diff": (True, True, True, True),
    "suggest": (True, True, True, False),
    "draft": (True, True, True, False),
    "source-diff": (True, True, True, True),
    "open-pr": (True, True, False, True),
    "screenshot-link": (True, True, True, True),
    "task": (True, True, True, False),
    "discuss": (True, True, True, True),
    "flag-source": (True, True, True, True),
    "source-review-queue": (True, True, False, True),
    "bulk-clear": (True, True, False, False),
    "apply-near": (True, True, False, False),
    "find-replace": (True, True, False, False),
    "rename-placeholder": (True, True, False, False),
    "scan-decide": (True, False, False, True),
    "patch": (True, False, False, True),
    "apply": (True, False, False, True),
    "analytics": (True, True, False, True),
    "metrics": (True, True, False, True),
    "concordance": (True, True, True, True),
    "tm-export": (True, True, True, True),
    "org": (True, True, True, True),
    "tm-import": (True, True, False, True),
    "glossary-export": (True, True, True, True),
    "glossary-import": (True, True, False, True),
    "glossary-propose": (True, True, False, True),
    "impact": (True, True, False, True),
    "pseudo": (True, True, False, True),
    "hard-keys": (True, True, False, True),
    "explain-scan": (True, True, True, True),
    "acknowledge-flush": (True, False, False, False),
    "init": (True, False, False, False),
    # Engine apply rewrites the project's models (ADR-156): Admin only, like init and the Settings page.
    "engine": (True, False, False, False),
    # Rewrites the project's queue blueprints (W3): Admin only, like init --taskqueue.
    "queue-engine": (True, False, False, False),
    # Recording the approach writes the project config (W6): Admin only, like engine and init.
    "approach": (True, False, False, False),
}


def normalize_role(role: str | None) -> str | None:
    if role is None:
        return None
    name = str(role).strip()
    for known in ROLES:
        if known.lower() == name.lower():
            return known
    return None


def _matrix_for(cfg: Any | None) -> dict[str, tuple[bool, bool, bool, bool]]:
    """Merge optional ``cfg.permission_matrix`` overrides; never grant Translator translate."""
    matrix = {op: tuple(flags) for op, flags in DEFAULT_MATRIX.items()}
    raw = getattr(cfg, "permission_matrix", None) if cfg is not None else None
    if not isinstance(raw, dict):
        return matrix  # type: ignore[return-value]
    for op, flags in raw.items():
        key = str(op).replace("_", "-")
        if key not in matrix or not isinstance(flags, (list, tuple)) or len(flags) != 4:
            continue
        merged = tuple(bool(x) for x in flags)
        if key == "translate":
            # ADR-39: overrides cannot grant Translator translate.
            merged = (merged[0], merged[1], False, merged[3])
        matrix[key] = merged  # type: ignore[assignment]
    return matrix  # type: ignore[return-value]


def role_allowed(
    role: str | None,
    operation: str,
    *,
    cfg: Any | None = None,
) -> bool:
    """Return True if ``role`` may run ``operation``. Admin always may."""
    name = normalize_role(role)
    if name is None:
        return False
    if name == ROLE_ADMIN:
        return True
    op = operation.replace("_", "-")
    flags = _matrix_for(cfg).get(op)
    if flags is None:
        return False
    try:
        idx = ROLES.index(name)
    except ValueError:
        return False
    return bool(flags[idx])


def task_scope_denied(
    cfg: Any | None, role: str | None, username: str | None, locale: str, refs: list[str],
) -> str:
    """Why a Translator may not write these keys, or ``""`` (C-029, ADR-93).

    Only with ``[tasks] contribute_in_tasks_only``: a Translator may write a key in a
    locale only when a task assigns that locale to them and lists the key. Every
    other role is unaffected. A Translator without a name (token session) gets nothing.
    """
    if cfg is None or not getattr(cfg, "tasks_only", False):
        return ""
    if normalize_role(role) != ROLE_TRANSLATOR:
        return ""
    from ..catalog.tasks import TaskStore

    allowed = TaskStore.for_project(cfg).assigned_keys(username or "", locale) if username else set()
    missing = [r for r in refs if r not in allowed]
    if not missing:
        return ""
    return f"{missing[0]} is not assigned to you in {locale} (tasks-only contributing)"


def deny_message(role: str | None, operation: str) -> str:
    op = operation.replace("_", "-")
    who = normalize_role(role) or (role or "anonymous")
    return f"role {who} cannot run {op}"
