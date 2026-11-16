"""ICU span translation and LLM output cleaning for the translate engine."""

from __future__ import annotations

import re
from collections.abc import Callable

from ..core.icu import is_bare_placeholder_span, split_top_level_segments, top_level_brace_spans
from ..providers import CompletionRequest, ProviderError, record_provider_spend
from .prompts import (
    build_fragment_prompt,
    build_icu_span_prompt,
)
from ._shared import WorkItem


from .placeholder_mask import mask_bare_placeholders, restore_placeholders

__all__: list[str] = []  # internal helpers; import names explicitly

Reporter = Callable[[str], None]


SHORT_WORD_LIMIT = 4
_FRAGMENT_TEXT_RE = re.compile(r"[A-Za-z]")
_EXPLANATION_PREFIX_RE = re.compile(
    r"^(?:"
    r"here is(?: the translation)?|translation|output|translated text|"
    r"oto(?: jest)? tłumaczenie|oto tłumaczenie"
    r")\s*[:—\-]\s*",
    re.IGNORECASE,
)


def _clean_llm_output(text: str) -> str:
    """Drop prompt echoes and keep a single-line fragment translation."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(("fragment:", "icu fragment:", "string to translate:")):
            continue
        line = _EXPLANATION_PREFIX_RE.sub("", line).strip()
        if line:
            return line
    return _EXPLANATION_PREFIX_RE.sub("", text.strip()).strip()


def _bill_cloud(cfg, provider, locale: str, model: str) -> None:
    """Record spend for a cloud call that already completed.

    Local kinds and allow_cloud are guarded inside record_provider_spend.
    Do not re-check remaining budget. A run that started under the cap can
    keep the same provider after the month is exhausted; those calls still cost.
    """
    record_provider_spend(cfg, provider, locale, model=model)


def _safe_glue_output(source_fragment: str, translated: str) -> str:
    """Keep glue safe — never let the model inject placeholder syntax."""
    if "{" in translated and "{" not in source_fragment:
        return source_fragment
    if "}" in translated and "}" not in source_fragment:
        return source_fragment
    return translated


# Per-run cache: identical ICU/text fragments reuse one LLM call.
_fragment_cache: dict[tuple[str, str, str], str | None] = {}


def clear_fragment_cache() -> None:
    _fragment_cache.clear()


def _complete_span(
    provider, prompt: str, llm_source: str, locale: str, model: str, cfg,
) -> str | None:
    cache_key = (locale, model, llm_source)
    if cache_key in _fragment_cache:
        return _fragment_cache[cache_key]
    try:
        text = provider.complete(CompletionRequest(
            prompt=prompt,
            model=model,
            timeout_s=cfg.provider.timeout_single_s,
            options={"target_lang": locale, "locale": locale},
            source_texts=[llm_source], target_locale=locale,
        ))
        _bill_cloud(cfg, provider, locale, model)
    except ProviderError:
        _fragment_cache[cache_key] = None
        return None
    piece = _clean_llm_output(text or "")
    out = piece or None
    _fragment_cache[cache_key] = out
    return out


def _translate_icu_span(
    provider, segment: str, language: str, locale: str, model: str, cfg,
    glossary_block: str, register: str, glossary: dict,
) -> str | None:
    from ..core.validate import validate_translation

    for strict in (False, True):
        prompt = build_icu_span_prompt(
            segment, language, locale, cfg.domain, glossary_block,
            register=register, strict=strict,
            style_notes=cfg.style_for(locale, model)[1],
        )
        piece = _complete_span(provider, prompt, segment, locale, model, cfg)
        if not piece:
            continue
        ok, _ = validate_translation(segment, piece, locale, glossary)
        if ok:
            return piece
    return _translate_select_branches(
        provider, segment, language, locale, model, cfg, glossary_block, register, glossary,
    )


_SELECT_HEAD = re.compile(r"^\{\s*(\w+)\s*,\s*select\s*,(.*)\}$", re.S)
_EDGE = re.compile(r"^([\s,;:·–—(\-]*)(.*?)([\s,;:.!?)·]*)$", re.S)


def _select_branches(segment: str) -> tuple[str, list[tuple[str, str]]] | None:
    """``{arg, select, k {body} …}`` -> (arg, [(k, body)]); None for nested messages."""
    m = _SELECT_HEAD.match(segment.strip())
    if not m:
        return None
    rest, out = m.group(2), []
    i = 0
    while i < len(rest):
        km = re.compile(r"\s*([\w=-]+)\s*\{").match(rest, i)
        if not km:
            return None if rest[i:].strip() else (m.group(1), out)
        depth, j = 1, km.end()
        while j < len(rest) and depth:
            depth += {"{": 1, "}": -1}.get(rest[j], 0)
            j += 1
        if depth:
            return None
        body = rest[km.end():j - 1]
        if any(not is_bare_placeholder_span(span) for span in top_level_brace_spans(body)):
            return None
        out.append((km.group(1), body))
        i = j
    return m.group(1), out


def _translate_select_branches(
    provider, segment, language, locale, model, cfg, glossary_block, register, glossary,
) -> str | None:
    """Rebuild a simple select span from its branch texts translated one by one.

    Attached modifiers (``{lone, select, yes {, alone} other {}}``) carry leading
    punctuation and empty branches that models drop when given the whole span. The
    structure, edge punctuation and empty branches are copied; only words go to the
    model (ADR-132).
    """
    parsed = _select_branches(segment)
    if not parsed:
        return None
    arg, branches = parsed
    rebuilt = []
    for key, body in branches:
        lead, core, trail = _EDGE.match(body).groups()
        if not re.search(r"[^\W\d_]", _PLACEHOLDER_STRIP.sub("", core)):
            rebuilt.append(f"{key} {{{body}}}")
            continue
        masked, ph_mask = mask_bare_placeholders(core)
        prompt = build_fragment_prompt(
            masked, language, cfg.domain, glossary_block, register=register,
            placeholder_mask=ph_mask or None, style_notes=cfg.style_for(locale, model)[1],
        )
        piece = _complete_span(provider, prompt, masked, locale, model, cfg)
        if not piece:
            return None
        piece = restore_placeholders(piece.strip().strip('"„”'), ph_mask)
        rebuilt.append(f"{key} {{{lead}{piece}{trail}}}")
    out = "{%s, select, %s}" % (arg, " ".join(rebuilt))
    from ..core.validate import validate_translation

    ok, _ = validate_translation(segment, out, locale, glossary)
    return out if ok else None


_PLACEHOLDER_STRIP = re.compile(r"\{[^{}]*\}")


_FENCE_RE = re.compile(r"^```[\w-]*\s*|\s*```$")


def _clean_icu_message_output(text: str, source: str) -> str:
    """One-line ICU message from a model reply: drop fences, labels and wrapping lines."""
    body = _FENCE_RE.sub("", (text or "").strip()).strip()
    if "\n" in source:
        return body
    lines = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("string to translate:", "icu message:")):
            continue
        lines.append(_EXPLANATION_PREFIX_RE.sub("", line).strip())
    if not lines:
        return ""
    first = lines[0]
    if first.count("{") == first.count("}"):
        return first
    # A model that pretty-printed the branches over several lines: join them back.
    return " ".join(lines)


def _translate_icu_whole(
    provider, payload, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
    rejection: str | None = None,
    attempts: int = 2,
) -> tuple[str | None, str | None, bool]:
    """Translate a plural/select message in one prompt (ADR-124).

    Returns ``(text, reason, provider_failed)``. ``text`` already passed the
    candidate gate (normalizer, V03 categories, V47 structure). A second attempt
    carries the first attempt's rejection reason.
    """
    from dataclasses import replace

    from ..core.standards import get_standard
    from .candidates import validate_candidate
    from .prompts import build_icu_message_prompt_parts

    reason = rejection
    for _ in range(max(1, attempts)):
        item = replace(payload, previous_rejection=reason) if reason else payload
        system, user = build_icu_message_prompt_parts(
            item, language, locale, cfg.domain, glossary_block,
            register=register, style_notes=cfg.style_for(locale, model)[1],
        )
        try:
            raw = provider.complete(CompletionRequest(
                prompt=user,
                system=system,
                model=model,
                timeout_s=cfg.provider.timeout_single_s,
                options={"target_lang": locale, "locale": locale},
                source_texts=[payload.source], target_locale=locale,
            ))
            _bill_cloud(cfg, provider, locale, model)
        except ProviderError as exc:
            report(f"    WARN: ICU whole-message provider error: {exc}")
            return None, reason, True
        text = _clean_icu_message_output(raw or "", payload.source)
        if not text:
            reason = "empty answer"
            continue
        checked, why = validate_candidate(
            payload.source, text, locale, glossary or {},
            placeholder_mask=payload.placeholder_mask,
            check_html=True if payload.html else None,
            standard=get_standard(getattr(cfg, "catalog_standard", None)),
        )
        if checked is not None:
            return checked, None, False
        reason = why
    return None, reason, False


def _translate_icu_decomposed(
    provider, payload, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
) -> str | None:
    """Translate ICU-heavy strings one top-level span at a time."""
    parts: list[str] = []
    for kind, segment in split_top_level_segments(payload.source):
        if kind == "icu" and is_bare_placeholder_span(segment):
            # Bare {name} tokens are code identifiers — never send to the LLM.
            parts.append(segment)
            continue
        ph_mask: dict[str, str] | None = None
        if kind == "text":
            if not _FRAGMENT_TEXT_RE.search(segment):
                parts.append(segment)
                continue
            masked, ph_mask = mask_bare_placeholders(segment)
            prompt = build_fragment_prompt(
                masked, language, cfg.domain, glossary_block, register=register,
                placeholder_mask=ph_mask or None,
                style_notes=cfg.style_for(locale, model)[1],
            )
            llm_source = masked
            try:
                piece = _complete_span(
                    provider, prompt, llm_source, locale, model, cfg,
                )
            except ProviderError as exc:
                report(f"    WARN: glue fragment error: {exc}")
                return None
            if not piece:
                return None
            piece = restore_placeholders(piece, ph_mask)
            piece = _safe_glue_output(segment, piece)
            lead = segment[: len(segment) - len(segment.lstrip())]
            trail = segment[len(segment.rstrip()) :]
            piece = f"{lead}{piece.strip()}{trail}"
            parts.append(piece)
            continue
        piece = _translate_icu_span(
            provider, segment, language, locale, model, cfg,
            glossary_block, register, glossary or {},
        )
        if not piece:
            report(f"    WARN: ICU span failed validation for fragment: {segment[:60]}...")
            return None
        parts.append(piece)
    return "".join(parts)

def _translate_icu_skeleton(
    provider, payload, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
) -> str | None:
    """Third ICU strategy (ADR-132): the sentence once, the ICU spans one by one.

    Fragment mode sends "Last hand (" and " made " to the model separately, which
    cannot be translated. Here every plural/select span is replaced by a token
    ``{__icuN}``, the whole sentence is translated as one frame (bare placeholders
    and tokens kept), each span is translated with the per-span prompt, and the
    result is reassembled and run through the full candidate gate.
    """
    from ..core.standards import get_standard
    from .candidates import validate_candidate

    spans: list[str] = []
    skeleton_parts: list[str] = []
    for kind, segment in split_top_level_segments(payload.source):
        if kind == "icu" and not is_bare_placeholder_span(segment):
            skeleton_parts.append("{__icu%d}" % len(spans))
            spans.append(segment)
        else:
            skeleton_parts.append(segment)
    if not spans:
        return None
    skeleton = "".join(skeleton_parts)
    masked, ph_mask = mask_bare_placeholders(skeleton)
    prompt = build_fragment_prompt(
        masked, language, cfg.domain, glossary_block, register=register,
        placeholder_mask=ph_mask or None, style_notes=cfg.style_for(locale, model)[1],
    )
    tokens = ["{__icu%d}" % i for i in range(len(spans))]
    sentence = None
    for attempt in range(2):
        if attempt:
            prompt += ("\n\nKeep every token " + " ".join(tokens)
                       + " exactly once, unchanged, where it belongs in the sentence.")
        try:
            got = _complete_span(provider, prompt, masked + ("" if not attempt else " "), locale,
                                 model, cfg)
        except ProviderError as exc:
            report(f"    WARN: ICU skeleton error: {exc}")
            return None
        got = restore_placeholders(got or "", ph_mask).strip()
        if got and all(got.count(t) == 1 for t in tokens):
            sentence = got
            break
    if sentence is None:
        report("    WARN: ICU skeleton lost or duplicated a span token")
        return None
    out = sentence
    for token, span in zip(tokens, spans):
        piece = _translate_icu_span(
            provider, span, language, locale, model, cfg, glossary_block, register, glossary or {},
        )
        if not piece:
            report(f"    WARN: ICU skeleton span failed: {span[:60]}...")
            return None
        out = out.replace(token, piece)
    checked, why = validate_candidate(
        payload.source, out, locale, glossary or {},
        placeholder_mask=payload.placeholder_mask,
        check_html=True if payload.html else None,
        standard=get_standard(getattr(cfg, "catalog_standard", None)),
    )
    if checked is None:
        report(f"    WARN: ICU skeleton result rejected: {why}")
    return checked
