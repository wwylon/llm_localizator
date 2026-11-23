"""Status operation."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

from ..catalog import StateStore, needs_translation, catalog_for
from ..catalog.history import HistoryStore
from ..catalog.provenance import provider_of, source_class
from ..catalog.state import state_key
from ..projects import ContextNotes, ProjectConfig
from .types import OpResult, StatusRequest


@dataclass
class LocaleStatus:
    locale: str
    total: int = 0
    translated: int = 0
    stale: int = 0
    missing: int = 0
    # Present in the target catalogue, differs from the source, but has no state record.
    # Counted apart from ``missing``: the text exists, only the record is absent (run ``adopt``).
    no_record: int = 0
    namespaces_missing: int = 0
    frozen: bool = False
    providers: dict[str, int] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    tm_reused: int = 0
    llm_generated: int = 0
    human_edited: int = 0
    agent_edited: int = 0
    imported: int = 0
    # (bucket, YYYY-MM-DD of the latest history event) per translated key.
    stage_days: list[tuple[str, str]] = field(default_factory=list)
    # (source class, YYYY-MM-DD of the latest history event) per translated key (C-031).
    source_days: list[tuple[str, str]] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return (self.translated / self.total) if self.total else 0.0


def leverage_bucket(entry: dict, trigger: str | None) -> str:
    """Where a translated key came from. Missing keys are not passed here.

    ``trigger`` is the latest history event, not a field on the state record.
    """
    provider = provider_of(entry)
    if provider == "import":
        return "imported"
    if provider == "agent":
        return "agent_edited"
    if provider == "human":
        return "human_edited"
    if trigger == "tm-hit":
        return "tm_reused"
    return "llm_generated"


def leverage_line(row: LocaleStatus) -> str:
    return (
        f"  leverage: tm={row.tm_reused} llm={row.llm_generated} "
        f"human={row.human_edited} agent={row.agent_edited} imported={row.imported}"
    )


def collect(cfg, catalog) -> list[LocaleStatus]:
    state = StateStore(cfg.state_dir) if cfg.state_dir else None
    history = HistoryStore(cfg.history_root())
    namespaces = cfg.namespaces_for(catalog)
    notes = ContextNotes(cfg.context_dir)

    out: list[LocaleStatus] = []
    for locale in cfg.targets:
        st = LocaleStatus(locale=locale, frozen=cfg.is_frozen(locale))
        provider_counts: Counter[str] = Counter()
        model_counts: Counter[str] = Counter()
        latest = history.latest_by_key(locale) if state is not None else {}
        buckets: Counter[str] = Counter()
        for ns in namespaces:
            source = catalog.load(cfg.source_locale, ns)
            if not source:
                continue
            if not catalog.path_for(locale, ns).exists():
                st.namespaces_missing += 1
            target = catalog.load(locale, ns)
            for key, src in source.items():
                if cfg.is_skipped(ns, key, src):
                    continue
                st.total += 1
                if key not in target:
                    st.missing += 1
                    continue
                entry = state.entry(locale, ns, key) if state else None
                if entry is None:
                    value = target.get(key)
                    if isinstance(value, str) and value.strip() and value != src:
                        st.no_record += 1
                    else:
                        st.missing += 1
                elif needs_translation(src, entry, **notes.stale_args(ns, key)):
                    st.stale += 1
                    provider_counts[provider_of(entry)] += 1
                    model_counts[str(entry.get("model") or "?")] += 1
                    event = latest.get(state_key(ns, key))
                    buckets[leverage_bucket(entry, event.trigger if event else None)] += 1
                else:
                    st.translated += 1
                    provider_counts[provider_of(entry)] += 1
                    model_counts[str(entry.get("model") or "?")] += 1
                    event = latest.get(state_key(ns, key))
                    bucket = leverage_bucket(entry, event.trigger if event else None)
                    buckets[bucket] += 1
                    st.stage_days.append((bucket, str(event.ts)[:10] if event else ""))
                    st.source_days.append((
                        source_class(provider_of(entry), event.trigger if event else None),
                        str(event.ts)[:10] if event else "",
                    ))
        st.tm_reused = buckets["tm_reused"]
        st.llm_generated = buckets["llm_generated"]
        st.human_edited = buckets["human_edited"]
        st.agent_edited = buckets["agent_edited"]
        st.imported = buckets["imported"]
        st.providers = dict(sorted(provider_counts.items()))
        # Top models only (keep payload small).
        st.models = dict(model_counts.most_common(8))
        out.append(st)
    return out


def collect_missing(cfg, catalog) -> dict[str, list[tuple[str, str, str]]]:
    """Return {locale: [(namespace, key, reason)]} where reason is 'missing' or 'stale'."""
    state = StateStore(cfg.state_dir) if cfg.state_dir else None
    namespaces = cfg.namespaces_for(catalog)
    notes = ContextNotes(cfg.context_dir)
    out: dict[str, list[tuple[str, str, str]]] = {}
    for locale in cfg.targets:
        items: list[tuple[str, str, str]] = []
        for ns in namespaces:
            source = catalog.load(cfg.source_locale, ns)
            if not source:
                continue
            target = catalog.load(locale, ns)
            for key, src in source.items():
                if cfg.is_skipped(ns, key, src):
                    continue
                if key not in target:
                    items.append((ns, key, "missing"))
                    continue
                entry = state.entry(locale, ns, key) if state else None
                if entry is None:
                    items.append((ns, key, "missing"))
                elif needs_translation(src, entry, **notes.stale_args(ns, key)):
                    items.append((ns, key, "stale"))
        out[locale] = items
    return out


def _file_collection_status(cfg: ProjectConfig, req: StatusRequest) -> OpResult:
    from ..projects.collections import get_collection, list_collection_files

    try:
        coll = get_collection(cfg, req.collection)
        files = list_collection_files(cfg, coll.name, list(cfg.targets))
    except ValueError as exc:
        return OpResult(ok=False, exit_code=64, command="status", summary=str(exc))
    lines = [f"{coll.name}: {len(files)} file(s)"]
    for row in files:
        stale = [
            loc for loc, item in row["locales"].items()
            if item["stale"] or not item["present"]
        ]
        note = f" stale/missing: {', '.join(stale)}" if stale else ""
        lines.append(f"  {row['path']}  coverage {row['coverage']:.0%}{note}")
    return OpResult(
        ok=True,
        exit_code=0,
        command="status",
        summary=f"{coll.name}: {len(files)} file(s)",
        lines=lines,
        data={"collection": coll.name, "files": files},
    )


NO_SCREEN = "(no screen)"


def screen_coverage(cfg: ProjectConfig, catalog) -> list[dict]:
    """Coverage per screen: one row per (screen, locale), least complete first.

    Single pass over source keys × locales (avoids a second ``collect_missing``
    walk that re-loaded every catalogue).
    """
    notes = ContextNotes(cfg.context_dir)
    state = StateStore(cfg.state_dir) if cfg.state_dir else None
    targets = list(cfg.targets)
    totals: Counter = Counter()
    open_keys: dict[tuple[str, str], int] = {}
    for ns in cfg.namespaces_for(catalog):
        source = catalog.load(cfg.source_locale, ns)
        if not source:
            continue
        targets_by_locale = {
            locale: catalog.load(locale, ns) for locale in targets
        }
        for key, src in source.items():
            if cfg.is_skipped(ns, key, src):
                continue
            screen = notes.screen(ns, key) or NO_SCREEN
            totals[screen] += 1
            stale_args = notes.stale_args(ns, key)
            for locale in targets:
                target = targets_by_locale[locale]
                if key not in target:
                    open_keys[(screen, locale)] = open_keys.get((screen, locale), 0) + 1
                    continue
                entry = state.entry(locale, ns, key) if state else None
                if entry is None or needs_translation(src, entry, **stale_args):
                    open_keys[(screen, locale)] = open_keys.get((screen, locale), 0) + 1
    rows = []
    for screen, total in totals.items():
        for locale in targets:
            pending = open_keys.get((screen, locale), 0)
            rows.append({
                "screen": screen, "locale": locale, "total": total,
                "pending": pending, "coverage": (total - pending) / total if total else 1.0,
            })
    rows.sort(key=lambda r: (r["coverage"], r["screen"], r["locale"]))
    return rows


def _status_by_screen(cfg: ProjectConfig, catalog) -> OpResult:
    rows = screen_coverage(cfg, catalog)
    lines = [
        f"{r['screen']} [{r['locale']}]: {r['coverage']:.1%} ({r['pending']} of {r['total']} pending)"
        for r in rows
    ]
    return OpResult(
        ok=True, exit_code=0, command="status",
        summary=f"{len(rows)} screen/locale row(s)", lines=lines,
        data={"project": cfg.name, "screens": rows},
    )


def op_status(cfg: ProjectConfig, req: StatusRequest, *, catalog=None) -> OpResult:
    if req.collection and req.collection != "messages":
        from ..projects.collections import get_collection
        from .content import op_content_status

        try:
            coll = get_collection(cfg, req.collection)
        except ValueError as exc:
            return OpResult(ok=False, exit_code=64, command="status", summary=str(exc))
        if coll.kind == "remote":
            return op_content_status(cfg, coll.name, missing=req.missing)
        return _file_collection_status(cfg, req)
    if catalog is None:
        catalog = catalog_for(cfg)
    if req.missing:
        missing_map = collect_missing(cfg, catalog)
        items = {
            loc: [{"namespace": ns, "key": k, "reason": r} for ns, k, r in rows]
            for loc, rows in missing_map.items()
        }
        total = sum(len(v) for v in items.values())
        lines = []
        for loc, rows in missing_map.items():
            if not rows:
                continue
            lines.append(f"{loc}: {len(rows)} key(s) need translation")
            for ns, key, reason in rows[:50]:
                lines.append(f"  [{reason}] {ns}.{key}")
        return OpResult(
            ok=True,
            exit_code=0,
            command="status",
            summary=f"{total} missing/stale key(s)",
            lines=lines,
            data={"project": cfg.name, "locales": items},
        )

    if req.by_screen:
        return _status_by_screen(cfg, catalog)
    rows = collect(cfg, catalog)
    lines = []
    for r in rows:
        line = (
            f"{r.locale}{' (frozen)' if r.frozen else ''}: "
            f"{r.coverage:.1%} ({r.translated} done, {r.stale} stale, {r.missing} missing"
            + (f", {r.no_record} with text but no record" if r.no_record else "")
            + ")"
        )
        if r.providers:
            prov = ", ".join(f"{k}={v}" for k, v in r.providers.items())
            line += f"  [{prov}]"
        lines.append(line)
        if r.models:
            models = ", ".join(f"{k}={v}" for k, v in r.models.items())
            lines.append(f"  models: {models}")
        lines.append(leverage_line(r))
    return OpResult(
        ok=True,
        exit_code=0,
        command="status",
        summary=f"{len(rows)} locale(s)",
        lines=lines,
        data={
            "project": cfg.name,
            "locales": [
                {k: v for k, v in asdict(r).items() if k not in ("stage_days", "source_days")}
                | {"coverage": r.coverage}
                for r in rows
            ],
        },
    )
