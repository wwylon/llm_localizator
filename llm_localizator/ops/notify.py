"""Opt-in completion webhooks (E.3 / ADR-40)."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import socket
import urllib.error
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "NOTIFY_FORMATS", "envelope", "notify_project", "notify_webhook", "notify_webhook_async",
    "read_delivery_log", "sign_body",
    "validate_webhook_url", "webhook_log_path",
]

_LOG_KEEP = 200
NOTIFY_FORMATS = ("json", "slack")


def envelope(payload: dict[str, Any], project: str = "") -> dict[str, Any]:
    """Standard ``{event, project, ts, data}`` body (ADR-40 addendum).

    The original flat fields stay at the top level so existing receivers keep working;
    ``data`` repeats them without the envelope keys.
    """
    event = str(payload.get("event") or ("op." + str(payload["command"]) if payload.get("command") else "event"))
    proj = str(payload.get("project") or project or "")
    data = {k: v for k, v in payload.items() if k not in ("event", "project")}
    return {
        **payload, "event": event, "project": proj,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": data,
    }


def _slack_body(env: dict[str, Any]) -> dict[str, Any]:
    detail = ", ".join(f"{k}={v}" for k, v in env["data"].items() if isinstance(v, (str, int, float)) and v != "")
    text = f"[{env['project']}] {env['event']}" + (f": {detail}" if detail else "")
    return {"text": text[:3000]}


def notify_project(cfg, payload: dict[str, Any], *, wait: bool = False) -> None:
    """Send *payload* to ``[notify] webhook`` of *cfg* in its configured format."""
    url = getattr(cfg, "notify_webhook", "") or ""
    if not url:
        return
    send = notify_webhook if wait else notify_webhook_async
    send(url, payload, log_path=webhook_log_path(cfg), project=getattr(cfg, "name", ""),
         fmt=getattr(cfg, "notify_format", "json") or "json")


def _allow_private() -> bool:
    return bool(os.environ.get("LLM_LOCALIZE_WEBHOOK_ALLOW_PRIVATE"))


def _ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, from_dns: bool) -> bool:
    """Whether *ip* is refused for webhook delivery.

    Literal loopback (``http://127.0.0.1/...``) stays allowed for local dogfood.
    The same address reached via DNS rebinding is refused unless private hooks
    are explicitly enabled — that is the SSRF case.
    """
    if _allow_private():
        return False
    if ip.is_loopback and not from_dns:
        return False
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    )


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            out.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    return out


def validate_webhook_url(url: str | None, *, resolve_dns: bool = False) -> str | None:
    """Return an error string if ``url`` is set but not a safe http(s) target.

    When ``resolve_dns`` is true (send path), hostnames are resolved and every
    address must be public unless ``LLM_LOCALIZE_WEBHOOK_ALLOW_PRIVATE`` is set.
    """
    text = (url or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "webhook URL must be http(s)"
    host = (parsed.hostname or "").strip("[]")
    if not host:
        return "webhook URL must be http(s)"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not resolve_dns:
            return None  # name checked at send time
        ips = _resolve_host_ips(host)
        if not ips:
            return "webhook URL host could not be resolved"
        if any(_ip_blocked(addr, from_dns=True) for addr in ips):
            return "webhook URL must not target a private or link-local address"
        return None
    if _ip_blocked(ip, from_dns=False):
        return "webhook URL must not target a private or link-local address"
    return None


def sign_body(body: bytes, secret: str) -> str:
    """``sha256=<hex>`` HMAC of the request body, for receiver verification."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def webhook_log_path(cfg) -> Path | None:
    """Where deliveries are logged for *cfg*, or ``None`` without a state root."""
    try:
        return cfg.state_root() / "webhook_log.jsonl"
    except Exception:  # noqa: BLE001 - logging is optional
        return None


def _redact(url: str) -> str:
    """Scheme, host and path only: query strings often carry tokens."""
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}{parts.path}"


def _log_delivery(log_path: Path | None, url: str, payload: dict, outcome: dict) -> None:
    if log_path is None:
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": _redact(url),
        "event": str(payload.get("event") or payload.get("command") or ""),
        **outcome,
    }
    try:
        from ..catalog.io import append_text_line, atomic_write_text

        append_text_line(log_path, json.dumps(row, ensure_ascii=False))
        # Read only once the file could hold more than twice _LOG_KEEP rows of about this row's size. M5: re-opening
        # a file just written costs ~30 ms on Windows, and every delivery paid it before.
        line = json.dumps(row, ensure_ascii=False)
        if Path(log_path).stat().st_size > _LOG_KEEP * 2 * len(line) * 0.8:
            lines = Path(log_path).read_text(encoding="utf-8").splitlines()
            if len(lines) > _LOG_KEEP * 2:
                atomic_write_text(Path(log_path), "\n".join(lines[-_LOG_KEEP:]) + "\n")
    except OSError:
        pass


def read_delivery_log(log_path: Path | None, limit: int = 50) -> list[dict]:
    """Newest-first delivery rows; unreadable lines are skipped."""
    if log_path is None:
        return []
    try:
        lines = Path(log_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def notify_webhook(
    url: str | None, payload: dict[str, Any], *, timeout: float = 5.0,
    log_path: Path | None = None, project: str = "", fmt: str = "",
) -> None:
    """POST ``payload`` when ``url`` is set. Never raises to the caller.

    Each attempt is appended to *log_path* (status or error, duration) when given.
    """
    text = (url or "").strip()
    if not text:
        return
    # Resolve DNS at send time so a public name cannot rebind to a private IP.
    refusal = validate_webhook_url(text, resolve_dns=True)
    if refusal is not None:
        _log_delivery(log_path, text, payload, {"ok": False, "error": refusal})
        return
    env = envelope(payload, project) if (fmt or project) else payload
    if fmt == "slack":
        body = json.dumps(_slack_body(env), ensure_ascii=False).encode("utf-8")
    else:
        body = json.dumps(env, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    secret = os.environ.get("LLM_LOCALIZE_WEBHOOK_SECRET", "")
    if secret and fmt != "slack":
        headers["X-LLM-Localizator-Signature"] = sign_body(body, secret)
    req = urllib.request.Request(
        text,
        data=body,
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout) as resp:
            resp.read()
            status = getattr(resp, "status", 0)
    except urllib.error.HTTPError as exc:
        _log_delivery(log_path, text, payload, {
            "ok": False, "status": exc.code, "error": f"HTTP {exc.code}",
            "ms": int((time.perf_counter() - started) * 1000),
        })
        return
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log_delivery(log_path, text, payload, {
            "ok": False, "error": str(getattr(exc, "reason", exc))[:200],
            "ms": int((time.perf_counter() - started) * 1000),
        })
        return
    _log_delivery(log_path, text, payload, {
        "ok": True, "status": status, "ms": int((time.perf_counter() - started) * 1000),
    })


def notify_webhook_async(
    url: str | None, payload: dict[str, Any], *, timeout: float = 5.0,
    log_path: Path | None = None, project: str = "", fmt: str = "",
) -> None:
    """Fire ``notify_webhook`` on a daemon thread so a slow hook never blocks an op."""
    if not (url or "").strip():
        return
    import threading

    threading.Thread(
        target=notify_webhook, args=(url, payload), kwargs={"timeout": timeout, "log_path": log_path, "project": project, "fmt": fmt},
        daemon=True, name="llm-localizator-webhook",
    ).start()
