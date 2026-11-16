"""Web session helpers and auth API payloads (ADR-39)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..ops.permissions import (
    ROLE_ADMIN,
    ROLE_SUPERVISOR,
    ROLE_TRANSLATOR,
    deny_message,
    role_allowed,
)
from ..projects.accounts import (
    STATUS_APPROVED,
    STATUS_PENDING,
    AccountStore,
    UserRecord,
)
from ..projects.config import ProjectConfig

__all__ = [
    "SESSION_COOKIE",
    "SESSION_HEADER",
    "Actor",
    "accounts_for",
    "actor_from_request",
    "editor_identity",
    "locale_allowed",
    "project_allowed",
    "require_mutation",
    "require_op",
    "resolve_locales",
]

SESSION_COOKIE = "llm_session"
SESSION_HEADER = "X-LLM-Session"


@dataclass
class Actor:
    """Resolved caller for a request."""

    kind: str  # "token_admin" | "user" | "anonymous"
    role: str | None = None
    user: UserRecord | None = None
    via_token: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN or self.kind == "token_admin"

    @property
    def approved(self) -> bool:
        if self.kind == "token_admin":
            return True
        return bool(
            self.user is not None
            and self.user.status == STATUS_APPROVED
            and self.role
        )


def accounts_for(cfg: ProjectConfig) -> AccountStore:
    return AccountStore(cfg.state_root())


def actor_from_request(
    cfg: ProjectConfig,
    *,
    session_token: str | None,
    startup_token: str | None,
    provided_startup: str | None,
    shell_token: str | None = None,
) -> Actor:
    """Prefer a user session; else the printed startup token → Admin.

    The browser shell gets a separate *shell token* from ``/api/bootstrap-token``. It only proves the request
    came from our own page (CSRF); it grants Admin solely while no user accounts exist (single-user mode).
    Once accounts exist, a logged-in Translator who drops the session cookie cannot become Admin with it.

    When the server has no startup token installed (tests / unlocked),
    an unauthenticated caller is treated as Admin so existing hermetic
    HTTP suites keep working.
    """
    store = accounts_for(cfg)
    user = store.user_for_session(session_token)
    if user is not None:
        return Actor(kind="user", role=user.role, user=user, via_token=False)
    if (
        startup_token
        and provided_startup
        and secrets_equal(startup_token, provided_startup)
    ):
        return Actor(kind="token_admin", role=ROLE_ADMIN, via_token=True)
    if (
        shell_token
        and provided_startup
        and secrets_equal(shell_token, provided_startup)
        and not store.list_users()
    ):
        return Actor(kind="token_admin", role=ROLE_ADMIN, via_token=True)
    if not startup_token:
        return Actor(kind="token_admin", role=ROLE_ADMIN, via_token=False)
    return Actor(kind="anonymous")


def secrets_equal(a: str, b: str) -> bool:
    import secrets

    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def editor_identity(actor: Actor) -> tuple[str | None, str | None]:
    """Session user id + username for history/activity stamps. Token → none."""
    if actor.kind == "user" and actor.user is not None:
        return actor.user.id, actor.user.username
    return None, None


def locale_allowed(actor: Actor, locale: str) -> bool:
    if actor.is_admin or actor.kind == "token_admin":
        return True
    if actor.user is None or actor.user.status != STATUS_APPROVED:
        return False
    if actor.role != ROLE_TRANSLATOR:
        # Supervisor / Developer: all locales for now (SPEC: supervisor per language —
        # chips still restrict when set).
        if actor.user.locales:
            return locale in actor.user.locales
        return True
    if not actor.user.locales:
        return False
    return locale in actor.user.locales


def resolve_locales(
    actor: Actor,
    requested: list[str] | None,
    targets: list[str],
) -> tuple[list[str], str | None]:
    """Intersect requested locales with the actor's allowance.

    Empty or missing ``requested`` means "every target this actor may see",
    never "every configured target". Returns ``(locales, error)``; error is a
    human message when a named locale is out of scope.
    """
    wanted = [str(x).strip() for x in (requested or []) if str(x).strip()]
    if not wanted:
        return [t for t in targets if locale_allowed(actor, t)], None
    for loc in wanted:
        if not locale_allowed(actor, loc):
            return [], f"locale {loc} is not allowed for this user"
    return wanted, None


def project_allowed(actor: Actor, project: str, default_project: str) -> bool:
    """Session Translators/Developers stay on the server default project.

    Token-admin, Admin, and Supervisor may switch catalogues. Accounts always
    live under the default project's state (ADR-39).
    """
    if actor.kind == "token_admin" or actor.is_admin:
        return True
    if actor.role == ROLE_SUPERVISOR:
        return True
    name = (project or "").strip() or default_project
    return name == default_project


def require_mutation(actor: Actor) -> dict[str, Any] | None:
    """Return an error payload if the actor may not mutate catalogues."""
    if actor.kind == "token_admin":
        return None
    if actor.user is None:
        return {"ok": False, "error": "authentication required"}
    if actor.user.status == STATUS_PENDING:
        return {"ok": False, "error": "account is pending approval"}
    if actor.user.status != STATUS_APPROVED or not actor.role:
        return {"ok": False, "error": "account is not approved"}
    return None


def require_op(actor: Actor, operation: str, *, cfg: ProjectConfig | None = None) -> dict[str, Any] | None:
    if actor.kind == "token_admin":
        return None
    denied = require_mutation(actor)
    if denied is not None:
        return denied
    if not role_allowed(actor.role, operation, cfg=cfg):
        return {
            "ok": False,
            "error": deny_message(actor.role, operation),
            "exit_code": 77,
        }
    return None


def public_me(actor: Actor) -> dict[str, Any]:
    if actor.kind == "token_admin":
        return {
            "ok": True,
            "authenticated": True,
            "via": "token",
            "role": ROLE_ADMIN,
            "user": None,
        }
    if actor.user is None:
        return {"ok": True, "authenticated": False, "via": None, "role": None, "user": None}
    return {
        "ok": True,
        "authenticated": True,
        "via": "session",
        "role": actor.role,
        "user": actor.user.to_public(),
        "pending": actor.user.status == STATUS_PENDING,
    }
