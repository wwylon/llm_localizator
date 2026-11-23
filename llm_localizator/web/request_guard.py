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


#: Sent on every response. The CSP is limited to what cannot break the pages (they
#: use inline scripts): no framing, no plugins, no foreign base or form targets.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"
    ),
}

#: Largest accepted POST body. Routes that carry files (imports, uploads, screenshots,
#: generic ops with embedded payloads) keep the old 32 MB; everything else is small JSON.
BODY_LIMIT_DEFAULT = 4_000_000
BODY_LIMIT_FILES = 32_000_000
_FILE_ROUTE_HINTS = ("import", "upload", "screenshot", "/api/ops/")


def max_body_bytes(path: str) -> int:
    lowered = path.lower()
    if any(hint in lowered for hint in _FILE_ROUTE_HINTS):
        return BODY_LIMIT_FILES
    return BODY_LIMIT_DEFAULT


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
    _owner_only(path)
    return token


def _owner_only(path) -> None:
    """Limit a secret file to the current user: mode 0600, or on Windows an ACL without inherited entries.

    ``chmod`` only toggles the read-only flag on Windows, so a token file there stayed readable by other local users.
    Best effort: a failure leaves the default permissions.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if os.name != "nt":
        return
    import getpass
    import subprocess

    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:(R,W)"],
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


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
