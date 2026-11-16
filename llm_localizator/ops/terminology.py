"""Read-only cross-locale glossary term report (review 6.2)."""

from __future__ import annotations

from ..catalog import build_catalog
from ..core.term_consistency import term_spreads
from ..core.validate import glossary_violations
from ..projects import ProjectConfig
from ..projects.context import effective_glossary_for
from .types import OpResult

__all__ = ["op_term_report"]


def op_term_report(cfg: ProjectConfig, *, locales: list[str] | None = None) -> OpResult:
    """Glossary gaps (V13 matcher, inflection-aware) and cross-key term spreads (V48).

    ``data["gaps"]`` lists keys whose source uses a term with an approved rendering the
    translation lacks; ``data["spreads"]`` lists terms rendered more than one way.
    """
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    glossary = effective_glossary_for(
        cfg.glossary_path,
        shared=list(getattr(cfg, "glossary_shared", []) or []),
        conflict=getattr(cfg, "glossary_conflict", "own"),
    )
    targets = [loc for loc in (locales or cfg.targets) if loc in cfg.targets]
    rows: dict[str, list] = {loc: [] for loc in targets}
    gaps: list[dict] = []
    for ns in cfg.namespaces_for(catalog):
        source = catalog.load(cfg.source_locale, ns)
        loaded = {locale: catalog.load(locale, ns) for locale in targets}
        for key, src in source.items():
            if not isinstance(src, str) or not src.strip():
                continue
            label = f"{ns}.{key}" if ns else key
            for locale in targets:
                raw = loaded[locale].get(key)
                if not isinstance(raw, str) or not raw.strip():
                    continue
                rows[locale].append((label, src, raw))
                for issue in glossary_violations(src, raw, glossary, locale):
                    if issue.kind in ("missing-approved", "forbidden-variant"):
                        gaps.append({"locale": locale, "key": label, "term": issue.term,
                                     "kind": issue.kind, "message": issue.message})
    spreads = [sp for loc in targets for sp in term_spreads(rows[loc], glossary, loc)]

    lines = [f"{g['locale']}	{g['key']}	{g['message']}" for g in gaps]
    for sp in spreads:
        counts = ", ".join(f"{r} {len(k)}" for r, k in sorted(
            sp.by_rendering.items(), key=lambda item: -len(item[1])))
        lines.append(f"{sp.locale}	V48 '{sp.term}'	{counts}"
                     + (f", unknown {len(sp.unknown)}" if sp.unknown else ""))
    parts = []
    if gaps:
        parts.append(f"{len(gaps)} glossary gap(s)")
    if spreads:
        parts.append(f"{len(spreads)} term(s) rendered inconsistently")
    return OpResult(
        ok=True, exit_code=0, command="term-report",
        summary=", ".join(parts) or "no glossary gaps",
        lines=lines,
        data={"gaps": gaps, "spreads": [sp.as_dict() for sp in spreads]},
    )
