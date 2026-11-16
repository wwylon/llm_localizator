"""Accounts store hardening: corrupt files, session hashing, lockout, rehash."""

from __future__ import annotations

import json

import pytest

from llm_localizator.projects import accounts as acc
from llm_localizator.projects.accounts import AccountStore, verify_password


def _store(tmp_path) -> AccountStore:
    acc._FAILURES.clear()
    return AccountStore(tmp_path)


def test_corrupt_users_file_is_never_overwritten_by_register(tmp_path) -> None:
    store = _store(tmp_path)
    (tmp_path / "users.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(acc.AccountStoreError):
        store.register("alice", "password-1")
    assert (tmp_path / "users.json").read_text(encoding="utf-8") == "{not json"


def test_sessions_are_hashed_at_rest(tmp_path) -> None:
    store = _store(tmp_path)
    store.register("alice", "password-1")
    user = store.authenticate("alice", "password-1")
    token = store.create_session(user)
    raw = (tmp_path / "sessions.json").read_text(encoding="utf-8")
    assert token not in raw
    assert AccountStore(tmp_path).user_for_session(token).username == "alice"


def test_deny_drops_the_users_sessions(tmp_path) -> None:
    store = _store(tmp_path)
    store.register("admin1", "password-1")
    store.register("bob", "password-2")
    bob = store.find_by_username("bob")
    store.set_role(bob.id, role="translator", locales=["pl"])
    token = store.create_session(bob)
    store.deny(bob.id)
    assert AccountStore(tmp_path).user_for_session(token) is None


def test_repeated_failures_lock_the_account(tmp_path) -> None:
    store = _store(tmp_path)
    store.register("alice", "password-1")
    for _ in range(acc.MAX_FAILURES):
        assert store.authenticate("alice", "wrong-pass") is None
    assert store.authenticate("alice", "password-1") is None  # locked
    acc._FAILURES.clear()
    assert store.authenticate("alice", "password-1") is not None


def test_malformed_hash_is_a_failed_login_not_a_crash() -> None:
    assert verify_password("x", "scrypt$zz$zz") is False


def test_legacy_hash_is_upgraded_on_login(tmp_path) -> None:
    store = _store(tmp_path)
    store.register("alice", "password-1")
    users = json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))
    import hashlib

    salt = bytes.fromhex("00" * 16)
    legacy = hashlib.scrypt(b"password-1", salt=salt, n=2**14, r=8, p=1, dklen=64)
    users["users"][0]["password_hash"] = f"scrypt${salt.hex()}${legacy.hex()}"
    (tmp_path / "users.json").write_text(json.dumps(users), encoding="utf-8")
    fresh = AccountStore(tmp_path)
    assert fresh.authenticate("alice", "password-1") is not None
    assert json.loads((tmp_path / "users.json").read_text())["users"][0]["password_hash"].startswith("scrypt2$")
