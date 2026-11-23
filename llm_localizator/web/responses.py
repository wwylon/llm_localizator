"""Response, cookie, session and CORS plumbing of the loopback web handler (split from ``server.py``)."""

from __future__ import annotations

import hashlib
import json
import logging
from urllib.parse import urlparse

from .server_logic import _CLIENT_GONE
from .request_guard import (
    SECURITY_HEADERS,
    _cors_origin,
    _safe_filename,
    _same_origin,
    _origin_allowed,
)

_LOG = logging.getLogger("llm_localizator.web")


class ResponseMixin:
    """Mixed into ``_Handler``: ``_send``, cookies, the acting user and the CORS rules. Needs ``self._state``."""

    def _send(self, payload, status: int = 200, content_type="application/json", *,
              no_cache: bool = False, filename: str | None = None,
              set_cookies: list[str] | None = None,
              extra_headers: dict[str, str] | None = None,
              cache_control: str | None = None, etag: bool = False) -> None:
        from . import timing as web_timing

        if payload is None:
            body = b""
        elif isinstance(payload, bytes):
            body = payload
        else:
            if isinstance(payload, dict) and content_type.startswith("application/json"):
                bare = json.dumps(payload).encode("utf-8")
                payload = web_timing.attach_timing(payload, response_bytes=len(bare))
            body = json.dumps(payload).encode("utf-8")
        if etag and status == 200:
            tag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
            extra_headers = {**(extra_headers or {}), "ETag": tag}
            if (self.headers.get("If-None-Match") or "").strip() == tag:
                status, body = 304, b""
        timing_hdr = web_timing.server_timing_header(len(body) if body else 0)
        if timing_hdr:
            extra_headers = {**(extra_headers or {}), "Server-Timing": timing_hdr}
            extra_headers.setdefault("Access-Control-Expose-Headers", "Server-Timing")
        # Optional gzip for large static JS/CSS when the client accepts it.
        encoding = None
        if (
            status == 200
            and body
            and len(body) >= 1024
            and (
                "javascript" in content_type
                or content_type.startswith("text/css")
                or content_type.startswith("application/json")
            )
            and "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        ):
            import gzip

            compressed = gzip.compress(body, compresslevel=6)
            if len(compressed) < len(body):
                body = compressed
                encoding = "gzip"
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if encoding:
                self.send_header("Content-Encoding", encoding)
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{_safe_filename(filename)}"')
            # Reflect Origin only for JSON API responses — never for HTML/shell
            # or static assets (startup token lives in /app HTML).
            origin = None
            if (content_type or "").startswith("application/json"):
                origin = self._cors_reflect()
            vary_parts = []
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                vary_parts.append("Origin")
            if encoding:
                vary_parts.append("Accept-Encoding")
            if vary_parts:
                self.send_header("Vary", ", ".join(vary_parts))
            if cache_control:
                self.send_header("Cache-Control", cache_control)
            elif no_cache:
                self.send_header("Cache-Control", "no-store")
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            sent = {key.lower() for key in (extra_headers or {})}
            for key, value in SECURITY_HEADERS.items():
                if key.lower() not in sent:
                    self.send_header(key, value)
            for cookie in set_cookies or []:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except _CLIENT_GONE:
            return
        finally:
            web_timing.clear()

    def _cookie(self, name: str) -> str | None:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, val = part.split("=", 1)
            if key.strip() == name:
                return val.strip()
        return None

    def _session_token(self) -> str | None:
        from .auth import SESSION_COOKIE, SESSION_HEADER

        return self.headers.get(SESSION_HEADER) or self._cookie(SESSION_COOKIE)

    def _accounts_cfg(self):
        """Identity store is always the server default project's state (ADR-39).

        The sidebar project switcher selects catalogues; it must not split
        ``users.json`` / sessions across projects or hide pending Approvals.
        """
        return self._state(self.default_project, check_access=False).cfg

    def _actor(self, cfg=None):
        from .auth import actor_from_request

        expected = getattr(self, "session_token", "") or ""
        return actor_from_request(
            self._accounts_cfg(),
            session_token=self._session_token(),
            startup_token=expected or None,
            provided_startup=self.headers.get("X-LLM-Token") or None,
            shell_token=getattr(self, "shell_token", "") or None,
        )

    def _needs_login(self) -> bool:
        """A page view by a browser without a session while user accounts exist (and the server is locked)."""
        if not (getattr(self, "session_token", "") or ""):
            return False  # unlocked test servers
        from .auth import accounts_for

        try:
            store = accounts_for(self._accounts_cfg())
            if store.user_for_session(self._session_token()) is not None:
                return False
            return bool(store.list_users())
        except Exception:
            _LOG.warning("account store unreadable; not requiring login", exc_info=True)
            return False  # an unreadable account store must not lock people out of the setup pages

    #: Routes a page on another local port may call: the login form and the read-only translator overlay lookups.
    _CORS_OPEN_PATHS = ("/api/auth/login", "/api/auth/register", "/api/translator-bundle", "/api/translator-lookup")

    def _cors_reflect(self) -> str | None:
        """The request's Origin when this response may be read cross-origin, else None.

        Same origin needs no CORS header. A page on another local port (an app that edits through
        ``[web] overlay_edit``) gets one only when that option is on, or for the login routes, so an
        unrelated local page cannot read catalogue data (GETs carry no token).
        """
        origin = _cors_origin(self.headers.get("Origin"))
        if not origin:
            return None
        if _same_origin(origin, self.headers.get("Host")):
            return origin
        if urlparse(self.path).path in self._CORS_OPEN_PATHS:
            return origin
        try:
            overlay = bool(getattr(self._state(self.default_project, check_access=False).cfg, "overlay_edit", False))
        except Exception:
            _LOG.debug("overlay_edit unknown for %s", self.path, exc_info=True)
            overlay = False
        return origin if overlay else None

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not _origin_allowed(self.headers.get("Origin")):
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        origin = self._cors_reflect()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LLM-Token, X-LLM-Session")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()
