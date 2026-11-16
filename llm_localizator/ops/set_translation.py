"""``llm-localizator set``: write one translation with the gate and the stamps (ADR-122).

Agents and scripts used to fix a single string by editing the catalogue and then
hand-calling the recording helpers, or by asking a person to save it in the web
editor, which stamps ``human``. ``set`` does it in one step:

* the candidate gate (normalizer, then V03/V43/V46/V47 and the other hard checks)
  runs on the text; a rejection is refused unless ``force``;
* the catalogue is written under the project mutation lock;
* state, scores and history get one event with provenance: ``--by agent``
  (default; ``status=agent``) or ``--by human`` (a person dictated the text).
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.mutation_lock import project_mutation_lock
from ..core.quality import score_translation
from ..pipeline.candidates import validate_candidate
from ..pipeline.recording import provenance_stores, record_candidate
from ..projects import ProjectConfig, load_glossary
from .types import OpResult

__all__ = ["op_set", "SET_BY"]

SET_BY = ("agent", "human")


def _split_key(cfg: ProjectConfig, catalog, key: str) -> tuple[str, str] | None:
    """``namespace.key`` or a flat key -> (namespace, key) that exists in the source."""
    namespaces = cfg.namespaces_for(catalog)
    for ns in namespaces:
        if ns and key.startswith(ns + "."):
            rest = key[len(ns) + 1:]
            if rest in catalog.load(cfg.source_locale, ns):
                return ns, rest
    for ns in namespaces:
        if key in catalog.load(cfg.source_locale, ns):
            return ns, key
    return None


def op_set(
    cfg: ProjectConfig, *, locale: str, key: str, text: str,
    by: str = "agent", model: str | None = None, force: bool = False,
) -> OpResult:
    command = "set"
    if by not in SET_BY:
        return OpResult(ok=False, exit_code=2, command=command,
                        summary=f"--by must be one of {', '.join(SET_BY)}")
    if locale == cfg.source_locale:
        return OpResult(ok=False, exit_code=2, command=command,
                        summary="set writes translations; edit the source catalogue directly")
    if locale not in set(cfg.targets) | set(getattr(cfg, "frozen", []) or []):
        return OpResult(ok=False, exit_code=2, command=command,
                        summary=f"{locale} is not a target locale of {cfg.name}")
    catalog = catalog_for(cfg)
    found = _split_key(cfg, catalog, key)
    if found is None:
        return OpResult(ok=False, exit_code=2, command=command,
                        summary=f"key {key!r} is not in the {cfg.source_locale} catalogue")
    ns, bare = found
    source = catalog.load(cfg.source_locale, ns)
    glossary = load_glossary(cfg.glossary_path)
    applied: list[str] = []
    checked, reason = validate_candidate(source[bare], text, locale, glossary, applied=applied)
    lines: list[str] = []
    if applied:
        lines.append(f"normalized: {', '.join(applied)}")
    if checked is None:
        if not force:
            return OpResult(ok=False, exit_code=1, command=command,
                            summary=f"rejected by the candidate gate: {reason}",
                            lines=lines + ["pass --force to write it anyway (it stays flagged in validate)"],
                            data={"reason": reason})
        checked = text.strip()
        lines.append(f"written despite the gate (--force): {reason}")
    previous = catalog.load(locale, ns).get(bare)
    if previous == checked:
        return OpResult(ok=True, exit_code=0, command=command,
                        summary=f"{locale} {key}: unchanged", lines=lines,
                        data={"key": key, "locale": locale, "text": checked, "changed": False})
    quality = score_translation(source[bare], checked, locale, glossary)
    stores = provenance_stores(cfg)
    with project_mutation_lock(cfg):
        catalog.write(locale, ns, {bare: checked}, source=source)
        record_candidate(
            state=stores.state, scores=stores.scores, history=stores.history,
            locale=locale, namespace=ns, key=bare, source=source[bare],
            previous=previous, text=checked,
            model=model or ("human" if by == "human" else "agent"),
            quality_score=quality.score, quality_signals=quality.signals,
            trigger="set", status=by, provider=by,
            dimensions=quality.dimensions, scorer=quality.scorer,
        )
        stores.state.save(locale)
        stores.scores.save(locale)
    lines.append(f"{locale} {key}: {previous!r} -> {checked!r} (stamped {by})")
    return OpResult(
        ok=True, exit_code=0, command=command, summary=f"{locale} {key}: written",
        lines=lines,
        data={"key": key, "locale": locale, "text": checked, "previous": previous,
              "changed": True, "by": by, "forced": reason is not None and force},
    )
