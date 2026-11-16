"""AccountStore behaviour: registration, roles, sessions, persistence, races."""

from __future__ import annotations

import threading

from llm_localizator.projects import accounts as acc
from llm_localizator.projects.accounts import AccountStore


def _store(tmp_path) -> AccountStore:
    acc._FAILURES.clear()
    return AccountStore(tmp_path)


def test_first_user_is_admin_later_users_pending(tmp_path) -> None:
    s = _store(tmp_path)
    a = s.register("alice", "password-1")
    b = s.register("bobby", "password-2")
    assert a["first"] and a["user"]["role"] == acc.ROLE_ADMIN
    assert not b["first"] and b["user"]["status"] == acc.STATUS_PENDING


def test_register_rejects_short_name_short_password_and_duplicates(tmp_path) -> None:
    s = _store(tmp_path)
    assert not s.register(" a ", "password-1")["ok"]
    assert not s.register("alice", "short")["ok"]
    assert s.register("alice", "password-1")["ok"]
    assert not s.register("alice", "password-2")["ok"]
    assert not s.register("ALICE", "password-2")["ok"]


def test_state_persists_across_store_instances(tmp_path) -> None:
    s = _store(tmp_path)
    s.register("alice", "password-1")
    token = s.create_session(s.authenticate("alice", "password-1"))
    s2 = AccountStore(tmp_path)
    assert s2.find_by_username("alice") is not None
    assert s2.user_for_session(token).username == "alice"


def test_wrong_password_and_unknown_user_fail(tmp_path) -> None:
    s = _store(tmp_path)
    s.register("alice", "password-1")
    assert s.authenticate("alice", "nope-nope-1") is None
    assert s.authenticate("ghost", "password-1") is None


def test_session_expiry_logout_and_empty_token(tmp_path) -> None:
    s = _store(tmp_path)
    s.register("alice", "password-1")
    user = s.authenticate("alice", "password-1")
    expired = s.create_session(user, ttl_s=-1)
    assert s.user_for_session(expired) is None
    live = s.create_session(user)
    assert s.user_for_session(live).id == user.id
    s.drop_session(live)
    assert s.user_for_session(live) is None
    assert s.user_for_session(None) is None and s.user_for_session("") is None
    s.drop_session(None)


def test_set_role_updates_locales_and_rejects_unknown_role_or_user(tmp_path) -> None:
    s = _store(tmp_path)
    s.register("alice", "password-1")
    bob = s.register("bobby", "password-2")["user"]
    res = s.set_role(bob["id"], role="translator", locales=["pl", "de"])
    assert res["ok"] and res["user"]["locales"] == ["pl", "de"]
    assert res["user"]["status"] == acc.STATUS_APPROVED
    assert not s.set_role(bob["id"], role="emperor")["ok"]
    assert not s.set_role("nosuchid", role="translator")["ok"]


def test_remove_drops_user_and_sessions_but_not_last_admin(tmp_path) -> None:
    s = _store(tmp_path)
    admin = s.register("alice", "password-1")["user"]
    bob = s.register("bobby", "password-2")["user"]
    s.set_role(bob["id"], role="translator", locales=["pl"])
    tok = s.create_session(s.authenticate("bobby", "password-2"))
    assert not s.remove(admin["id"])["ok"]
    assert s.remove(bob["id"])["ok"]
    assert s.find_by_id(bob["id"]) is None and s.user_for_session(tok) is None
    assert not s.remove("nosuchid")["ok"]


def test_concurrent_registration_creates_exactly_one_admin(tmp_path) -> None:
    s = _store(tmp_path)
    results: list[dict] = []

    def go(i: int) -> None:
        results.append(AccountStore(tmp_path).register(f"user{i}", "password-1"))

    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(r["ok"] for r in results)
    users = s.list_users()
    assert len(users) == 6
    assert sum(1 for u in users if u.role == acc.ROLE_ADMIN) == 1
