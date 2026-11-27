"""OTA catalogue bundle for loopback clients (H.2 / ADR-40)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ..catalog import build_catalog
from ..projects import ProjectConfig

__all__ = ["bundle_payload", "etag_matches"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bundle_payload(
    cfg: ProjectConfig,
    *,
    locale: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    """Return catalogue JSON for one locale, with a content etag."""
    loc = (locale or "").strip()
    if not loc:
        return {"ok": False, "error": "locale is required"}
    allowed = {cfg.source_locale, *(getattr(cfg, "targets", None) or [])}
    if loc not in allowed:
        return {"ok": False, "error": f"unknown locale {loc!r}"}
    if namespace and namespace not in set(build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    ).namespaces()):
        return {"ok": False, "error": f"unknown namespace {namespace!r}"}
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    namespaces = [namespace] if namespace else list(catalog.namespaces())
    messages: dict[str, dict[str, str]] = {}
    ok = None
    if getattr(cfg, "delivery_require", "none") != "none" and loc != cfg.source_locale:
        from ..catalog.approval import approval_checker

        ok = approval_checker(cfg)
    for ns in namespaces:
        if not ns:
            continue
        flat = catalog.load(loc, ns)
        if ok is not None:
            src = catalog.load(cfg.source_locale, ns)
            flat = {k: (v if ok(loc, ns, k) else src.get(k, v)) for k, v in flat.items()}
        messages[ns] = {str(k): str(v) for k, v in flat.items()}
    body = {
        "ok": True,
        "locale": loc,
        "generated_at": _now_iso(),
        "messages": messages,
    }
    # Stable digest over messages only (not the timestamp).
    digest_src = json.dumps(
        {"locale": loc, "messages": messages},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    etag = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()[:32]
    body["etag"] = etag
    return body


def etag_matches(provided: str | None, etag: str) -> bool:
    if not provided or not etag:
        return False
    raw = provided.strip()
    if raw.startswith("W/"):
        raw = raw[2:].strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        raw = raw[1:-1]
    return raw == etag or provided.strip() == etag or provided.strip() == f'"{etag}"'
