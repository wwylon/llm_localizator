"""Emit an agent-ready backlog of keys that still need translation (no LLM)."""

from __future__ import annotations

from ..catalog.io import atomic_write_text
from ..projects.paths import project_path

from collections import defaultdict
from ..catalog import build_catalog
from ..projects import ProjectConfig
from .catalogue_gaps import GAP_REASONS, CatalogueGap, iter_catalogue_gaps
from .types import AgentBacklogRequest, OpResult, resolve_namespaces

__all__ = ["format_agent_prompt", "op_agent_backlog"]


def _catalog_path_hint(cfg: ProjectConfig, locale: str, namespace: str) -> str:
    """Relative path template filled for this locale/namespace."""
    path = cfg.catalog_path.replace("{locale}", locale)
    if "{namespace}" in path:
        path = path.replace("{namespace}", namespace or "_")
    return path.replace("\\", "/")


def format_agent_prompt(
    cfg: ProjectConfig,
    gaps: list[CatalogueGap],
    *,
    include_existing: bool = False,
) -> str:
    """Paste-ready markdown for a Cursor / AI agent localization pass."""
    if not gaps:
        return (
            f"# Localization backlog — {cfg.name}\n\n"
            "No keys need translation for the selected scope.\n"
        )

    by_locale: dict[str, list[CatalogueGap]] = defaultdict(list)
    for g in gaps:
        by_locale[g.locale].append(g)

    parts: list[str] = []
    for locale, rows in by_locale.items():
        path_example = _catalog_path_hint(cfg, locale, "{namespace}")
        parts.append(f"# Localization backlog — {cfg.name} / {locale}")
        parts.append("")
        parts.append(
            f"Translate {cfg.source_locale} → {locale}. "
            f"Edit `{path_example}` (one file per namespace)."
        )
        parts.append(
            "Preserve ICU placeholders (`{name}`, `#`, select/plural arms) and HTML. "
            "Do not invent keys absent from the English source. "
            "Write plain text: no backslash escapes, and never leave English words in a "
            "translation."
        )
        parts.append("After writing catalogue values, run:")
        parts.append(f"`llm-localizator adopt {cfg.name} --locales {locale}`")
        parts.append("")

        by_ns: dict[str, list[CatalogueGap]] = defaultdict(list)
        for g in rows:
            by_ns[g.namespace].append(g)

        for ns, ns_rows in sorted(by_ns.items()):
            rel = _catalog_path_hint(cfg, locale, ns)
            parts.append(f"## {ns or '(default)'} ({len(ns_rows)} keys) — `{rel}`")
            parts.append("")
            for g in ns_rows:
                label = f"{g.namespace}.{g.key}" if g.namespace else g.key
                parts.append(f"### {label}")
                parts.append(f"reason: {g.reason}")
                parts.append(f"EN: {g.source!r}")
                if include_existing and g.target is not None:
                    parts.append(f"current: {g.target!r}")
                parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def op_agent_backlog(cfg: ProjectConfig, req: AgentBacklogRequest) -> OpResult:
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    namespaces = resolve_namespaces(req.namespace, req.namespaces)
    reasons = req.reasons
    if reasons:
        unknown = set(reasons) - GAP_REASONS
        if unknown:
            return OpResult(
                ok=False,
                exit_code=64,
                command="agent-backlog",
                summary=f"unknown reason(s): {sorted(unknown)}",
            )

    gaps = list(
        iter_catalogue_gaps(
            cfg,
            locales=req.locales,
            namespaces=namespaces,
            reasons=reasons,
            limit=req.limit,
            catalog=catalog,
        )
    )

    items = [
        {
            "locale": g.locale,
            "namespace": g.namespace,
            "key": g.key,
            "reason": g.reason,
            "source": g.source,
            "target": g.target if req.include_existing else None,
            "path": _catalog_path_hint(cfg, g.locale, g.namespace),
        }
        for g in gaps
    ]
    prompt = format_agent_prompt(
        cfg, gaps, include_existing=req.include_existing,
    )

    by_reason: dict[str, int] = defaultdict(int)
    by_locale: dict[str, int] = defaultdict(int)
    for g in gaps:
        by_reason[g.reason] += 1
        by_locale[g.locale] += 1

    lines = [
        f"{loc}: {n} key(s)"
        for loc, n in sorted(by_locale.items())
    ]
    for reason, n in sorted(by_reason.items()):
        lines.append(f"  {reason}={n}")

    if req.split:
        return _split_backlog(cfg, req, gaps)

    fmt = (req.fmt or "prompt").lower()
    data = {
        "project": cfg.name,
        "count": len(gaps),
        "byLocale": dict(by_locale),
        "byReason": dict(by_reason),
        "keys": items,
        "prompt": prompt,
    }

    if fmt == "json":
        return OpResult(
            ok=True,
            exit_code=0,
            command="agent-backlog",
            summary=f"{len(gaps)} key(s) in backlog",
            lines=lines,
            data=data,
        )

    return OpResult(
        ok=True,
        exit_code=0,
        command="agent-backlog",
        summary=f"{len(gaps)} key(s) in backlog",
        lines=prompt.splitlines(),
        data=data,
    )


def _split_backlog(cfg: ProjectConfig, req: AgentBacklogRequest, gaps: list) -> OpResult:
    """One prompt file per locale or namespace, each chunked to the token budget (ADR-105)."""
    from pathlib import Path

    from .report_split import est_tokens

    if req.split not in ("locale", "namespace"):
        return OpResult(ok=False, exit_code=64, command="agent-backlog",
                        summary="--split must be locale or namespace")
    groups: dict[str, list] = {}
    for g in gaps:
        groups.setdefault(g.locale if req.split == "locale" else g.namespace or "(root)", []).append(g)
    # Engine data home by default, never the consumer repo (ADR-112).
    out_dir = project_path(cfg.root, req.out_dir) or Path(cfg.data_root()) / "reports" / "backlog"
    out_dir.mkdir(parents=True, exist_ok=True)
    budget = max(req.budget_tokens, 500)
    entries, keep = [], set()
    for name in sorted(groups):
        chunks, cur = [], []
        for g in groups[name]:
            cur.append(g)
            if est_tokens(format_agent_prompt(cfg, cur, include_existing=req.include_existing)) > budget and len(cur) > 1:
                chunks.append(cur[:-1])
                cur = [g]
        if cur:
            chunks.append(cur)
        for n, chunk in enumerate(chunks, 1):
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            fname = f"backlog-{req.split}-{safe}-{n}.md"
            text = format_agent_prompt(cfg, chunk, include_existing=req.include_existing)
            atomic_write_text(out_dir / fname, text)
            keep.add(fname)
            entries.append({"group": name, "part": n, "of": len(chunks), "file": fname,
                            "keys": len(chunk), "estTokens": est_tokens(text)})
    import json

    index_path = out_dir / "backlog-index.json"
    # Remove only parts an earlier run of this op listed in its own index: a folder the caller names may hold
    # other files that happen to match backlog-*.md.
    try:
        previous = {e.get("file") for e in json.loads(index_path.read_text(encoding="utf-8")).get("parts", [])}
    except (OSError, ValueError, AttributeError):
        previous = set()
    for name in previous - keep:
        if isinstance(name, str) and name.startswith("backlog-") and "/" not in name and "\\" not in name:
            (out_dir / name).unlink(missing_ok=True)
    atomic_write_text(index_path, json.dumps({"project": cfg.name, "split": req.split, "parts": entries}, indent=2))
    return OpResult(
        ok=True, exit_code=0, command="agent-backlog",
        summary=f"{len(gaps)} key(s) in {len(entries)} part(s) under {out_dir}",
        lines=[f"{e['file']}  {e['keys']} keys  ~{e['estTokens']} tokens" for e in entries],
        data={"project": cfg.name, "count": len(gaps), "parts": entries, "outDir": str(out_dir)},
    )
