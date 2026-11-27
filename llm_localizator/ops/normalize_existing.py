"""``llm-localizator normalize``: apply the candidate normalizer to existing catalogue values.

New model output already goes through :func:`core.normalize.normalize_candidate`
(wrapper quotes, ICU branch quotes, ``...`` -> ``…`` when the source uses ``…``,
first-letter case, plural fill, spelled-out symbols). Values written before that
existed, or by hand, keep those slips. This applies the same deterministic fixes to
what is already in the catalogue.

Safe by default: report only. ``write=True`` writes the catalogue under the project
mutation lock and records one history event per key (``trigger="normalize"``),
keeping the key's existing status and provenance (a fix is not a new translation).
Verified and locked keys are never touched: a person approved that exact text.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..catalog import catalog_for
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import is_verified, state_key
from ..core.normalize import normalize_candidate
from ..pipeline.recording import provenance_stores, record_candidate
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["op_normalize", "NormalizeFix", "plan_fixes", "DEFAULT_STEPS", "OPT_IN_STEPS"]

#: Steps with one right answer given the source; applied by default.
DEFAULT_STEPS = ("quotes", "icu_quotes", "ellipsis", "symbol", "plural_fill")
#: Steps that can undo a deliberate human choice on existing text (a capital a reviewer
#: kept, a second line on purpose); only with ``steps=`` naming them.
OPT_IN_STEPS = ("case", "first_line")


@dataclass(frozen=True)
class NormalizeFix:
    locale: str
    namespace: str
    key: str
    before: str
    after: str
    steps: tuple[str, ...]


def _keep_outer_whitespace(original: str, fixed: str) -> str:
    """The normalizer strips; keep the value's own leading/trailing whitespace."""
    lead = original[: len(original) - len(original.lstrip())]
    trail = original[len(original.rstrip()):]
    return f"{lead}{fixed}{trail}"


def plan_fixes(
    cfg: ProjectConfig, catalog, state, locales: list[str], namespaces: list[str] | None,
    steps_allowed: tuple[str, ...] = DEFAULT_STEPS,
) -> tuple[list[NormalizeFix], int, int]:
    """Fixes to make, protected keys skipped, and keys skipped for an opt-in step.

    The normalizer applies its steps together, so a value whose fix needs a step
    outside *steps_allowed* is left alone (and counted) rather than half-fixed.
    """
    allowed = set(steps_allowed)
    fixes: list[NormalizeFix] = []
    protected = 0
    needs_opt_in = 0
    for locale in locales:
        entries = state.load(locale) if state is not None else {}
        for ns in namespaces or cfg.namespaces_for(catalog):
            source = catalog.load(cfg.source_locale, ns)
            target = catalog.load(locale, ns)
            for key, value in target.items():
                src = source.get(key)
                if not isinstance(src, str) or not isinstance(value, str) or not value.strip():
                    continue
                fixed, steps = normalize_candidate(src, value, locale)
                if not steps:
                    continue
                if not set(steps) <= allowed:
                    needs_opt_in += 1
                    continue
                fixed = _keep_outer_whitespace(value, fixed)
                if fixed == value:
                    continue
                entry = entries.get(state_key(ns, key)) or {}
                if is_verified(entry) or entry.get("locked"):
                    protected += 1
                    continue
                fixes.append(NormalizeFix(locale, ns, key, value, fixed, tuple(steps)))
    return fixes, protected, needs_opt_in


def op_normalize(
    cfg: ProjectConfig, *, locales: list[str] | None = None,
    namespaces: list[str] | None = None, write: bool = False,
    steps: list[str] | None = None,
) -> OpResult:
    command = "normalize"
    known = set(DEFAULT_STEPS) | set(OPT_IN_STEPS)
    steps_allowed = tuple(steps) if steps else DEFAULT_STEPS
    unknown = sorted(set(steps_allowed) - known)
    if unknown:
        return OpResult(ok=False, exit_code=64, command=command,
                        summary=f"unknown step(s) {unknown}; known: {sorted(known)}")
    catalog = catalog_for(cfg)
    stores = provenance_stores(cfg)
    targets = cfg.resolve_locales(locales)
    fixes, protected, needs_opt_in = plan_fixes(
        cfg, catalog, stores.state, targets, namespaces, steps_allowed,
    )

    lines = [
        f"{f.locale} {(f.namespace + '.') if f.namespace else ''}{f.key} [{', '.join(f.steps)}]: "
        f"{f.before!r} -> {f.after!r}"
        for f in fixes
    ]
    if protected:
        lines.append(f"skipped {protected} verified or locked key(s): a person approved that text")
    if needs_opt_in:
        lines.append(
            f"skipped {needs_opt_in} value(s) whose fix also needs an opt-in step "
            f"({', '.join(s for s in OPT_IN_STEPS if s not in steps_allowed)}); "
            "review them, then add --steps to include it"
        )
    data = {
        "steps": list(steps_allowed),
        "needs_opt_in": needs_opt_in,
        "fixes": [
            {"locale": f.locale, "namespace": f.namespace, "key": f.key,
             "before": f.before, "after": f.after, "steps": list(f.steps)}
            for f in fixes
        ],
        "protected": protected,
        "written": False,
    }
    if not fixes:
        return OpResult(ok=True, exit_code=0, command=command,
                        summary="nothing to normalize", lines=lines, data=data)
    if not write:
        return OpResult(ok=True, exit_code=0, command=command,
                        summary=f"{len(fixes)} value(s) would change; pass --write to apply",
                        lines=lines, data=data)

    grouped: dict[tuple[str, str], list[NormalizeFix]] = {}
    for f in fixes:
        grouped.setdefault((f.locale, f.namespace), []).append(f)
    with project_mutation_lock(cfg):
        for (locale, ns), group in grouped.items():
            source = catalog.load(cfg.source_locale, ns)
            catalog.write(locale, ns, {f.key: f.after for f in group}, source=source)
            entries = stores.state.load(locale)
            for f in group:
                entry = entries.get(state_key(ns, f.key)) or {}
                record_candidate(
                    state=stores.state, scores=stores.scores, history=stores.history,
                    locale=locale, namespace=ns, key=f.key, source=source[f.key],
                    previous=f.before, text=f.after,
                    model=str(entry.get("model") or "normalize"),
                    quality_score=float(entry.get("quality_score") or 0.0),
                    quality_signals=[f"normalize:{s}" for s in f.steps],
                    trigger="normalize",
                    status=str(entry.get("status") or "machine"),
                    provider=entry.get("provider"),
                    record_score=False,  # a cosmetic fix does not re-score the key
                )
        for locale in {f.locale for f in fixes}:
            stores.state.save(locale)
    data["written"] = True
    return OpResult(ok=True, exit_code=0, command=command,
                    summary=f"normalized {len(fixes)} value(s)", lines=lines, data=data)
