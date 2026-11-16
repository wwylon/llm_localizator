"""Explain why a key is skipped / request-only / review-gated (Wave E)."""

from __future__ import annotations

from dataclasses import dataclass

from ..catalog import catalog_for
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["ExplainSkipRequest", "op_explain_skip", "explain_key"]


@dataclass
class ExplainSkipRequest:
    namespace: str | None = None
    key: str | None = None
    locale: str | None = None
    limit: int = 50


def explain_key(cfg: ProjectConfig, namespace: str, key: str, source: str | None = None) -> dict:
    """Return a machine-readable reason for skip / place policy."""
    reasons: list[str] = []
    if key in cfg.skip_keys:
        reasons.append("skip_keys")
    policy = cfg.place_policy(namespace, key) if cfg.places else cfg.places_default
    if policy == "never":
        reasons.append("place:never")
    elif policy == "request":
        reasons.append("place:request")
    elif policy == "review":
        reasons.append("place:review")
    if cfg.exclude_keys:
        from ..core.keyglob import key_glob_matches

        matched = [g for g in cfg.exclude_keys if key_glob_matches(g, namespace, key)]
        if matched:
            reasons.append("exclude_keys:" + ",".join(matched[:3]))
    if isinstance(source, str) and source and cfg.exclude_source:
        if any(r.search(source) for r in cfg.exclude_source):
            reasons.append("exclude_source")
    ns = (namespace or "").replace("\\", "/").strip("/")
    for raw in cfg.skip_namespaces:
        skip = str(raw).replace("\\", "/").strip("/")
        if skip and (ns == skip or ns.startswith(skip + "/")):
            reasons.append(f"skip_namespaces:{skip}")
            break
    skipped = cfg.is_skipped(namespace, key, source)
    return {
        "namespace": namespace,
        "key": key,
        "skipped": skipped,
        "requestOnly": cfg.is_request_only(namespace, key),
        "placePolicy": policy,
        "reasons": reasons,
    }


def op_explain_skip(cfg: ProjectConfig, req: ExplainSkipRequest) -> OpResult:
    catalog = catalog_for(cfg)
    rows: list[dict] = []
    if req.namespace and req.key:
        source = catalog.load(cfg.source_locale, req.namespace).get(req.key)
        src = source if isinstance(source, str) else None
        rows.append(explain_key(cfg, req.namespace, req.key, src))
    else:
        ns_list = [req.namespace] if req.namespace else cfg.namespaces_for(catalog)
        limit = max(1, min(int(req.limit or 50), 500))
        for ns in ns_list:
            source_map = catalog.load(cfg.source_locale, ns)
            for key, src in source_map.items():
                text = src if isinstance(src, str) else None
                if not cfg.is_skipped(ns, key, text) and not cfg.is_request_only(ns, key):
                    if not (cfg.places and cfg.place_policy(ns, key) == "review"):
                        continue
                rows.append(explain_key(cfg, ns, key, text))
                if len(rows) >= limit:
                    break
            if len(rows) >= limit:
                break
    summary = f"{len(rows)} key(s) with skip/place reasons"
    return OpResult(
        ok=True,
        exit_code=0,
        command="explain-skip",
        summary=summary,
        lines=[
            f"{r['namespace']}.{r['key']}: {', '.join(r['reasons']) or '—'}"
            for r in rows[:80]
        ],
        data={"rows": rows, "count": len(rows)},
    )
