"""Loopback request guards and the session token (split from server_logic)."""

from __future__ import annotations

import os
import re
import secrets
from urllib.parse import urlparse

from ..projects import ProjectConfig


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    return re.fullmatch(r"https?://(?:127\.0\.0\.1|localhost)(?::\d+)?", origin) is not None


def _safe_filename(name: str) -> str:
    """Strip characters that could break out of a quoted Content-Disposition value."""
    return re.sub(r'[\x00-\x1f\x7f"\\;/]', "_", str(name))[:200] or "download"


def _host_allowed(host: str | None) -> bool:
    """Loopback Host only: a DNS-rebinding page reaches us under its own name."""
    if not host:
        return True  # HTTP/1.0 clients; the socket is loopback-bound anyway
    return re.fullmatch(
        r"(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?", host.strip(), re.IGNORECASE,
    ) is not None


def _same_origin(origin: str | None, host: str | None) -> bool:
    if not origin:
        return True
    return urlparse(origin).netloc.lower() == (host or "").lower()


def _install_session_token(cfg: ProjectConfig) -> str:
    """Print and persist the POST token. Mode 0600 where the OS allows it."""
    token = secrets.token_urlsafe(32)
    path = cfg.state_root() / "web.token"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def rotate_web_token(handler_cls: type, cfg: ProjectConfig) -> str:
    """Replace the in-memory token and print the new value once."""
    token = _install_session_token(cfg)
    handler_cls.session_token = token
    handler_cls.shell_token = secrets.token_urlsafe(32)  # pages fetch a fresh one from /api/bootstrap-token
    print(f"  token: {token}")
    return token


def _cors_origin(origin: str | None) -> str | None:
    if origin and _origin_allowed(origin):
        return origin
    return None
