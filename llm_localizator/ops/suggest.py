"""``suggest``: one model translation for one key, returned and never stored (ADR-53).

Unlike ``translate`` this writes nothing: no catalogue value, no state, no history, no TM.
A person who likes the text pastes it into the editor and saves it, which stamps it as a
human edit (ADR-48).
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..core.cldr import language_name
from ..pipeline.ambiguity import ambiguity_notes
from ..pipeline.scoring import score_candidate
from ..pipeline._shared import WorkItem, _item_glossary, _payload
from ..pipeline.translate import _translate_payload
from ..projects import ContextNotes, ProjectConfig, glossary_prompt_block
from ..providers import ProviderError, provider_for_locale
from .translate import _cloud_block
from .types import OpResult, SuggestRequest, TranslateRequest

__all__ = ["op_suggest"]


def _fail(summary: str, code: int = 64) -> OpResult:
    return OpResult(ok=False, exit_code=code, command="suggest", summary=summary, lines=[summary])


def op_suggest(cfg: ProjectConfig, req: SuggestRequest) -> OpResult:
    locale, namespace, key = req.locale, req.namespace, req.key
    if not (locale and namespace and key):
        return _fail("suggest needs locale, namespace and key")
    if locale not in cfg.targets:
        return _fail(f"unknown target locale {locale!r}")
    catalog = catalog_for(cfg)
    source = catalog.load(cfg.source_locale, namespace).get(key)
    if not isinstance(source, str) or not source.strip():
        return _fail(f"{namespace}.{key} has no source text")
    blocked = _cloud_block(cfg, TranslateRequest(
        locales=[locale], namespace=namespace, keys=[f"{namespace}.{key}"],
    ))
    if blocked is not None:
        blocked.command = "suggest"
        return blocked

    notes = ContextNotes(cfg.context_dir)
    item = WorkItem(namespace=namespace, locale=locale, key=key, source=source)
    glossary = _item_glossary(cfg, notes, item)
    language = language_name(locale)
    model = cfg.model_for(locale)
    from ..catalog.cloud_cost import paying_cloud_kind, resolve_translation_model

    kind = paying_cloud_kind(cfg, locale)
    if kind:
        model = resolve_translation_model(cfg, locale, kind)
    register, _style = cfg.style_for(locale)
    lines: list[str] = []
    try:
        provider = provider_for_locale(cfg, locale, report=lines.append)
        payload = _payload(
            cfg, catalog, notes, {}, cfg.pivots.get(locale), item,
            None, {}, locale, glossary=glossary,
        )
        prompt_block = glossary_prompt_block(glossary, locale, language, sources=[source])

        def _run(mdl: str) -> str:
            return _translate_payload(
                provider, payload, language, locale, mdl, cfg, prompt_block,
                register, lines.append, glossary=glossary, llm_score=False,
            )

        text = _run(model)
    except ProviderError as exc:
        return _fail(f"model unavailable: {exc}", 1)
    if not text:
        return _fail("the model returned no usable text", 1)
    quality = score_candidate(
        provider, source=source, translated=text, locale=locale, language=language,
        glossary=glossary, cfg=cfg, max_chars=payload.max_chars, message_key=key,
        context=payload.context, llm_score=False,
    )
    out_lines = [text]
    data = {
        "text": text, "score": quality.score, "dimensions": quality.dimensions or {},
        "signals": list(quality.signals), "model": model,
    }
    if req.alternatives:
        data["alternatives"] = _alternatives(
            cfg, locale, model, text, kind, _run, lambda t: score_candidate(
                provider, source=source, translated=t, locale=locale, language=language,
                glossary=glossary, cfg=cfg, max_chars=payload.max_chars, message_key=key,
                context=payload.context, llm_score=False,
            ), out_lines,
        )
    if req.ambiguity and not kind:
        data["ambiguity"] = ambiguity_notes(
            provider, model, source=source, translated=text, language=language,
            context=payload.context or "", cfg=cfg, locale=locale,
        )
        out_lines += [f"ambiguous: {n['term']} -> {n['chosen']}" for n in data["ambiguity"]]
    if req.explain:
        explain = _explain(payload, provider, model, register)
        data["explain"] = explain
        out_lines += ["", "Why this result:"] + _explain_lines(explain)
    return OpResult(
        ok=True, exit_code=0, command="suggest", summary="suggestion ready", lines=out_lines,
        data=data,
    )


MAX_ALTERNATIVES = 2


def _alternatives(cfg, locale, used: str, text: str, cloud_kind, run, score, out_lines) -> list[dict]:
    """Candidates from the other configured roles (secondary, then the roster default).

    Same provider and prompt, different model; a model already used, or one that
    returns the same text, is skipped. A failing model is skipped, not fatal. Cloud
    projects get none: each extra model would be another paid call (ADR-35).
    """
    if cloud_kind:
        return []
    role = cfg.role_for(locale)
    pool = [role.secondary, role.primary, cfg.models.get(locale), cfg.models.get("default")]
    tried, seen_text, out = {used}, {text.strip()}, []
    for mdl in pool:
        if not mdl or mdl in tried or len(out) >= MAX_ALTERNATIVES:
            continue
        tried.add(mdl)
        try:
            alt = run(mdl)
        except ProviderError:
            continue
        if not alt or alt.strip() in seen_text:
            continue
        seen_text.add(alt.strip())
        q = score(alt)
        out.append({"text": alt, "score": q.score, "model": mdl, "signals": list(q.signals)})
        out_lines.append(f"alternative ({mdl}): {alt}")
    return out


def _pairs(rows) -> list[dict]:
    return [{"source": str(a), "target": str(b)} for a, b in (rows or [])]


def _explain(payload, provider, model: str, register: str) -> dict:
    """What fed the prompt, as plain data. Never carries URLs, keys or the full prompt."""
    return {
        "provider": str(getattr(provider, "kind", "") or type(provider).__name__),
        "model": model,
        "register": payload.register or register,
        "risk": payload.risk,
        "context": payload.context,
        "note": payload.llm_note,
        "fileNote": payload.file_note,
        "glossary": payload.glossary_note,
        "examples": _pairs(payload.examples),
        "siblings": _pairs(payload.siblings),
        "pivot": {"locale": payload.pivot_locale, "text": payload.pivot} if payload.pivot else None,
        "maxChars": payload.max_chars,
        "missingContext": list(payload.incomplete or []),
        "trace": list(payload.trace),
    }


def _explain_lines(explain: dict) -> list[str]:
    rows = [
        f"  model: {explain['model']} ({explain['provider']}), register {explain['register']}",
        f"  risk: {explain['risk']}",
    ]
    for label, key in (("context", "context"), ("note", "note"), ("file note", "fileNote"),
                       ("glossary", "glossary")):
        if explain[key]:
            rows.append(f"  {label}: {explain[key]}")
    if explain["maxChars"]:
        rows.append(f"  max length: {explain['maxChars']} characters")
    if explain["pivot"]:
        rows.append(f"  pivot ({explain['pivot']['locale']}): {explain['pivot']['text']}")
    for label, key in (("example", "examples"), ("same-screen", "siblings")):
        for pair in explain[key]:
            rows.append(f"  {label}: {pair['source']} -> {pair['target']}")
    for reason in explain["missingContext"]:
        rows.append(f"  missing context: {reason}")
    for entry in explain["trace"]:
        rows.append(f"  trace: {entry}")
    return rows
