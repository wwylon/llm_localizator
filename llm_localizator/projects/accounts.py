"""Local operator accounts in the consumer state dir (ADR-39)."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..catalog.io import atomic_write_text
from ..catalog.state import now_iso
from ..ops.permissions import (
    ROLE_ADMIN,
    normalize_role,
)
from ..catalog.io import read_json

__all__ = [
    "STATUS_PENDING",
    "STATUS_APPROVED",
    "STATUS_DENIED",
    "UserRecord",
    "AccountStore",
    "hash_password",
    "verify_password",
    "AccountStoreError",
    "MAX_FAILURES",
]

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"

_SCRYPT_N = 2**14           # legacy "scrypt$" hashes
_SCRYPT2_N = int(os.environ.get("LLM_LOCALIZE_SCRYPT_N") or 2**15)  # current "scrypt2$" hashes
_SCRYPT_MAXMEM = 128 * 1024 * 1024
MAX_FAILURES = 5
_LOCK_WINDOW_S = 900.0
_LOCK_S = 60.0
_MUTEX = threading.RLock()
# (state dir, username) -> (failure count, first failure time). In-process: the
# server is one process, and a restart clearing it is an acceptable trade-off.
_FAILURES: dict[tuple[str, str], tuple[int, float]] = {}


class AccountStoreError(RuntimeError):
    """The identity files exist but cannot be read; refusing to overwrite them."""
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Return ``scrypt$<salt_hex>$<hash_hex>``."""
    if not password:
        raise ValueError("password is required")
    salt_b = salt or secrets.token_bytes(16)
    try:
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt_b,
            n=_SCRYPT2_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_SCRYPT_DKLEN,
            maxmem=_SCRYPT_MAXMEM,
        )
    except AttributeError:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt_b, 260000, dklen=_SCRYPT_DKLEN,
        )
        return f"pbkdf2${salt_b.hex()}${digest.hex()}"
    return f"scrypt2${salt_b.hex()}${digest.hex()}"


def needs_rehash(encoded: str) -> bool:
    return encoded.startswith("scrypt$")


def _session_key(token: str) -> str:
    """Sessions are stored by digest so a leaked sessions.json grants nothing."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, salt_hex, digest_hex = encoded.split("$", 2)
    except ValueError:
        return False
    try:
        salt_b = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    if kind in ("scrypt", "scrypt2"):
        try:
            digest = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt_b,
                n=_SCRYPT_N if kind == "scrypt" else _SCRYPT2_N,
                r=_SCRYPT_R,
                p=_SCRYPT_P,
                dklen=_SCRYPT_DKLEN,
                maxmem=_SCRYPT_MAXMEM,
            )
        except (AttributeError, ValueError):
            return False
    elif kind == "pbkdf2":
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt_b, 260000, dklen=_SCRYPT_DKLEN,
        )
    else:
        return False
    return secrets.compare_digest(digest.hex(), digest_hex)


@dataclass
class UserRecord:
    id: str
    username: str
    password_hash: str
    status: str = STATUS_PENDING
    role: str | None = None
    locales: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "status": self.status,
            "role": self.role,
            "locales": list(self.locales),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> UserRecord | None:
        try:
            return cls(
                id=str(raw["id"]),
                username=str(raw["username"]),
                password_hash=str(raw["password_hash"]),
                status=str(raw.get("status") or STATUS_PENDING),
                role=raw.get("role"),
                locales=[str(x) for x in (raw.get("locales") or [])],
                created_at=str(raw.get("created_at") or ""),
                updated_at=str(raw.get("updated_at") or ""),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class SessionRecord:
    token: str
    user_id: str
    created_at: str
    expires_at: float


class AccountStore:
    """``{state}/users.json`` + ``{state}/sessions.json``."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.users_path = self.state_dir / "users.json"
        self.sessions_path = self.state_dir / "sessions.json"
        self._users: list[UserRecord] | None = None
        self._users_unreadable = False
        self._sessions: dict[str, SessionRecord] | None = None

    def _load_users(self) -> list[UserRecord]:
        if self._users is not None:
            return self._users
        out: list[UserRecord] = []
        if self.users_path.exists():
            try:
                raw = read_json(self.users_path)
            except (OSError, ValueError):
                raw = []
                self._users_unreadable = True
            if isinstance(raw, dict):
                raw = raw.get("users") or []
            for item in raw or []:
                if isinstance(item, dict):
                    user = UserRecord.from_dict(item)
                    if user is not None:
                        out.append(user)
        self._users = out
        return out

    def _save_users(self, users: list[UserRecord]) -> None:
        if self._users_unreadable:
            raise AccountStoreError(
                f"{self.users_path} is unreadable; fix or restore it before changing accounts"
            )
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {"users": [asdict(u) for u in users]}
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(self.users_path, text)
        try:
            os.chmod(self.users_path, 0o600)
        except OSError:
            pass
        self._users = users

    def _load_sessions(self) -> dict[str, SessionRecord]:
        if self._sessions is not None:
            return self._sessions
        out: dict[str, SessionRecord] = {}
        now = time.time()
        if self.sessions_path.exists():
            try:
                raw = read_json(self.sessions_path)
            except (OSError, json.JSONDecodeError):
                raw = []
            if isinstance(raw, dict):
                raw = raw.get("sessions") or []
            for item in raw or []:
                if not isinstance(item, dict):
                    continue
                try:
                    expires = float(item["expires_at"])
                    if expires < now:
                        continue
                    rec = SessionRecord(
                        token=str(item["token"]),
                        user_id=str(item["user_id"]),
                        created_at=str(item.get("created_at") or ""),
                        expires_at=expires,
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                out[rec.token] = rec  # already a digest
        self._sessions = out
        return out

    def _save_sessions(self, sessions: dict[str, SessionRecord]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": [
                {
                    "token": s.token,
                    "user_id": s.user_id,
                    "created_at": s.created_at,
                    "expires_at": s.expires_at,
                }
                for s in sessions.values()
            ],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(self.sessions_path, text)
        try:
            os.chmod(self.sessions_path, 0o600)
        except OSError:
            pass
        self._sessions = sessions

    def _reload(self) -> None:
        """Drop caches so a mutation starts from what is on disk (other instances write too)."""
        self._users = None
        self._users_unreadable = False
        self._sessions = None
        self._load_users()
        if self._users_unreadable:
            raise AccountStoreError(
                f"{self.users_path} is unreadable; fix or restore it before changing accounts"
            )

    def list_users(self) -> list[UserRecord]:
        return list(self._load_users())

    def find_by_username(self, username: str) -> UserRecord | None:
        key = username.strip().lower()
        for user in self._load_users():
            if user.username.lower() == key:
                return user
        return None

    def find_by_id(self, user_id: str) -> UserRecord | None:
        for user in self._load_users():
            if user.id == user_id:
                return user
        return None

    def register(self, username: str, password: str) -> dict[str, Any]:
        with _MUTEX:
            self._reload()
            return self._register(username, password)

    def _register(self, username: str, password: str) -> dict[str, Any]:
        name = username.strip()
        if not name or len(name) < 2:
            return {"ok": False, "error": "username is required"}
        if len(password) < 8:
            return {"ok": False, "error": "password must be at least 8 characters"}
        if self.find_by_username(name) is not None:
            return {"ok": False, "error": "username already exists"}
        users = self._load_users()
        ts = now_iso()
        first = len(users) == 0
        user = UserRecord(
            id=secrets.token_hex(8),
            username=name,
            password_hash=hash_password(password),
            status=STATUS_APPROVED if first else STATUS_PENDING,
            role=ROLE_ADMIN if first else None,
            locales=[],
            created_at=ts,
            updated_at=ts,
        )
        users.append(user)
        self._save_users(users)
        return {"ok": True, "user": user.to_public(), "first": first}

    _DUMMY_HASH = hash_password("timing-equaliser")

    def _fail_key(self, username: str) -> tuple[str, str]:
        return (str(self.state_dir), username.strip().lower())

    def is_locked(self, username: str) -> bool:
        count, first = _FAILURES.get(self._fail_key(username), (0, 0.0))
        if count < MAX_FAILURES:
            return False
        if time.time() - first > _LOCK_S:
            _FAILURES.pop(self._fail_key(username), None)
            return False
        return True

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        if self.is_locked(username):
            return None
        user = self.find_by_username(username)
        # Unknown users still pay for a hash so timing does not reveal them.
        ok = verify_password(password, user.password_hash if user else self._DUMMY_HASH)
        key = self._fail_key(username)
        if user is None or not ok:
            count, first = _FAILURES.get(key, (0, 0.0))
            now = time.time()
            if count == 0 or now - first > _LOCK_WINDOW_S:
                count, first = 0, now
            _FAILURES[key] = (count + 1, first)
            return None
        _FAILURES.pop(key, None)
        if needs_rehash(user.password_hash):
            with _MUTEX:
                try:
                    self._reload()
                    fresh = self.find_by_id(user.id)
                    if fresh is not None:
                        fresh.password_hash = hash_password(password)
                        self._save_users(self._load_users())
                        user = fresh
                except (AccountStoreError, OSError):
                    pass  # upgrade is opportunistic; the login itself succeeded
        return user

    def create_session(self, user: UserRecord, *, ttl_s: int = 86400 * 14) -> str:
        with _MUTEX:
            self._sessions = None
            return self._create_session(user, ttl_s)

    def _create_session(self, user: UserRecord, ttl_s: int) -> str:
        sessions = self._load_sessions()
        token = secrets.token_urlsafe(32)
        now = time.time()
        sessions[_session_key(token)] = SessionRecord(
            token=_session_key(token),
            user_id=user.id,
            created_at=now_iso(),
            expires_at=now + ttl_s,
        )
        self._save_sessions(sessions)
        return token

    def _drop_user_sessions(self, user_id: str) -> None:
        sessions = self._load_sessions()
        kept = {k: v for k, v in sessions.items() if v.user_id != user_id}
        if len(kept) != len(sessions):
            self._save_sessions(kept)

    def drop_session(self, token: str | None) -> None:
        if not token:
            return
        sessions = self._load_sessions()
        key = _session_key(token)
        if key in sessions:
            del sessions[key]
            self._save_sessions(sessions)

    def user_for_session(self, token: str | None) -> UserRecord | None:
        if not token:
            return None
        sessions = self._load_sessions()
        key = _session_key(token)
        rec = sessions.get(key)
        if rec is None:
            return None
        if rec.expires_at < time.time():
            # Drop in memory only — every authenticated request used to rewrite
            # sessions.json here. Persist on login/logout/create/drop instead.
            del sessions[key]
            self._sessions = sessions
            return None
        return self.find_by_id(rec.user_id)

    def prune_expired_sessions(self) -> int:
        """Rewrite sessions.json without expired rows. Returns how many were dropped."""
        sessions = self._load_sessions()
        now = time.time()
        kept = {k: v for k, v in sessions.items() if v.expires_at >= now}
        dropped = len(sessions) - len(kept)
        if dropped:
            self._save_sessions(kept)
        return dropped

    def set_role(
        self,
        user_id: str,
        *,
        role: str,
        locales: list[str] | None = None,
        status: str = STATUS_APPROVED,
    ) -> dict[str, Any]:
        known = normalize_role(role)
        if known is None:
            return {"ok": False, "error": f"unknown role {role!r}"}
        with _MUTEX:
            self._reload()
            return self._set_role(user_id, known, locales, status)

    def _set_role(self, user_id, known, locales, status) -> dict[str, Any]:
        users = self._load_users()
        for user in users:
            if user.id != user_id:
                continue
            user.role = known
            user.status = status
            if locales is not None:
                user.locales = [str(x) for x in locales]
            user.updated_at = now_iso()
            self._save_users(users)
            return {"ok": True, "user": user.to_public()}
        return {"ok": False, "error": "user not found"}

    def deny(self, user_id: str) -> dict[str, Any]:
        with _MUTEX:
            self._reload()
            return self._deny(user_id)

    def _deny(self, user_id: str) -> dict[str, Any]:
        users = self._load_users()
        for user in users:
            if user.id != user_id:
                continue
            user.status = STATUS_DENIED
            user.role = None
            user.updated_at = now_iso()
            self._save_users(users)
            self._drop_user_sessions(user_id)
            return {"ok": True, "user": user.to_public()}
        return {"ok": False, "error": "user not found"}

    def remove(self, user_id: str) -> dict[str, Any]:
        with _MUTEX:
            self._reload()
            return self._remove(user_id)

    def _remove(self, user_id: str) -> dict[str, Any]:
        users = self._load_users()
        target = None
        for user in users:
            if user.id == user_id:
                target = user
                break
        if target is None:
            return {"ok": False, "error": "user not found"}
        if (
            target.role == ROLE_ADMIN
            and target.status == STATUS_APPROVED
            and sum(
                1 for u in users
                if u.role == ROLE_ADMIN and u.status == STATUS_APPROVED
            ) <= 1
        ):
            return {"ok": False, "error": "cannot remove the last Admin"}
        remaining = [u for u in users if u.id != user_id]
        self._save_users(remaining)
        sessions = self._load_sessions()
        dropped = {k: v for k, v in sessions.items() if v.user_id != user_id}
        if len(dropped) != len(sessions):
            self._save_sessions(dropped)
        return {"ok": True}

    def invite_path(self) -> str:
        return "/register"
