"""The browser's shell token proves same-origin; it is Admin only while no accounts exist (M0, audit ops #1)."""

from __future__ import annotations

from types import SimpleNamespace

from llm_localizator.projects.accounts import AccountStore
from llm_localizator.web import auth

STARTUP = "printed-startup-token"
SHELL = "shell-token-from-bootstrap"


def _actor(tmp_path, provided, monkeypatch):
    monkeypatch.setattr(auth, "accounts_for", lambda cfg: AccountStore(tmp_path))
    return auth.actor_from_request(
        SimpleNamespace(), session_token=None, startup_token=STARTUP, provided_startup=provided, shell_token=SHELL,
    )


def test_single_user_mode_shell_token_is_admin(tmp_path, monkeypatch) -> None:
    assert _actor(tmp_path, SHELL, monkeypatch).is_admin


def test_with_accounts_shell_token_grants_nothing(tmp_path, monkeypatch) -> None:
    AccountStore(tmp_path).register("alice", "password-1")
    actor = _actor(tmp_path, SHELL, monkeypatch)
    assert actor.kind == "anonymous" and not actor.is_admin


def test_printed_startup_token_stays_admin_with_accounts(tmp_path, monkeypatch) -> None:
    AccountStore(tmp_path).register("alice", "password-1")
    assert _actor(tmp_path, STARTUP, monkeypatch).is_admin


def test_wrong_token_is_anonymous(tmp_path, monkeypatch) -> None:
    assert _actor(tmp_path, "nope", monkeypatch).kind == "anonymous"
