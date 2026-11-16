"""Localization Quality Score judge (ADR-20).

Asks an instruction-following model for structured dimension scores. Pure
combination math lives in :func:`lqs_from_judgment`; I/O is in
:func:`judge_translation`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..core.cldr import language_name
from ..core.quality import QualityResult
from ..core.validate import check_max_chars, validate_translation
from ..providers import CompletionRequest, Provider, ProviderError, complete_for

__all__ = [
    "JUDGE_SCHEMA",
    "JudgeResult",
    "build_judge_prompt",
    "parse_judge_response",
    "lqs_from_judgment",
    "judge_translation",
]

JUDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "semantic_accuracy": {"type": "number"},
        "fluency": {"type": "number"},
        "terminology": {"type": "number"},
        "ui_appropriateness": {"type": "number"},
        "missing_information": {"type": "boolean"},
        "added_information": {"type": "boolean"},
        "wrong_language": {"type": "boolean"},
        "placeholder_error": {"type": "boolean"},
        "html_error": {"type": "boolean"},
        "grammar_error": {"type": "boolean"},
        "style_error": {"type": "boolean"},
        "suggested_translation": {},
        "explanation": {"type": "string"},
    },
    "required": [
        "semantic_accuracy", "fluency", "terminology", "ui_appropriateness",
    ],
}

_WEIGHTS = {
    "semantic": 0.35,
    "info": 0.15,
    "fluency": 0.15,
    "terminology": 0.10,
    "ui": 0.10,
    "placeholders": 0.05,
    "html": 0.05,
    "length": 0.05,
}


@dataclass
class JudgeResult:
    ok: bool
    judgment: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


#: Signal prefix carrying the judge's ``suggested_translation`` (see ``suggestion_of``).
SUGGESTION_PREFIX = "judge suggests: "


def suggestion_of(signals) -> str | None:
    """The judge's suggested translation recorded in a score's signals, if any."""
    for sig in signals or []:
        if isinstance(sig, str) and sig.startswith(SUGGESTION_PREFIX):
            return sig[len(SUGGESTION_PREFIX):]
    return None


def build_judge_prompt(
    *,
    source: str,
    translated: str,
    language: str,
    domain: str,
    glossary_block: str = "",
    message_key: str = "",
    context: str = "",
    source_locale: str = "en",
    locale: str = "",
) -> str:
    key_line = f"Message key: {message_key}\n" if message_key else ""
    ctx_line = f"UI context: {context}\n" if context else ""
    gloss = f"{glossary_block}\n" if glossary_block else ""
    src_lang = language_name(source_locale)
    grammar = ""
    if locale:
        from .prompts import grammar_block

        rules = grammar_block(locale)
        if rules:
            grammar = f"Set grammar_error to true when the translation breaks these rules.\n{rules}"
    return (
        f"You are a localization quality judge for {domain}.\n"
        f"Evaluate whether the {language} translation is accurate, natural, and "
        f"suitable for a product UI.\n"
        f"{gloss}{grammar}{key_line}{ctx_line}"
        f"\n"
        f"Source ({src_lang}):\n{source}\n"
        f"\n"
        f"Translation ({language}):\n{translated}\n"
        f"\n"
        f"Return ONLY a JSON object with these fields:\n"
        f'  "semantic_accuracy": 0-100,\n'
        f'  "fluency": 0-100,\n'
        f'  "terminology": 0-100,\n'
        f'  "ui_appropriateness": 0-100,\n'
        f'  "missing_information": true/false,\n'
        f'  "added_information": true/false,\n'
        f'  "wrong_language": true/false,\n'
        f'  "placeholder_error": true/false,\n'
        f'  "html_error": true/false,\n'
        f'  "grammar_error": true/false,\n'
        f'  "style_error": true/false,\n'
        f'  "suggested_translation": string or null,\n'
        f'  "explanation": short string\n'
        f"\n"
        f"Score harshly on meaning errors. Prefer null for suggested_translation "
        f"unless you are confident in a fix that preserves ICU placeholders.\n"
    )


def _clamp_100(value: Any, default: float = 50.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, n))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return default


def parse_judge_response(raw: str) -> JudgeResult:
    text = (raw or "").strip()
    if not text:
        return JudgeResult(False, error="empty judge response")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return JudgeResult(False, error="judge response not JSON")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return JudgeResult(False, error="judge response not JSON")
    if not isinstance(data, dict):
        return JudgeResult(False, error="judge response not an object")
    return JudgeResult(True, judgment=data)


def lqs_from_judgment(
    judgment: dict[str, Any],
    *,
    source: str,
    translated: str,
    max_chars: int | None = None,
) -> tuple[float, dict[str, float], list[str]]:
    """Return ``(score, dimensions_0_to_1, signals)`` from a parsed judgment."""
    signals: list[str] = []
    semantic = _clamp_100(judgment.get("semantic_accuracy")) / 100.0
    fluency = _clamp_100(judgment.get("fluency")) / 100.0
    terminology = _clamp_100(judgment.get("terminology")) / 100.0
    ui = _clamp_100(judgment.get("ui_appropriateness")) / 100.0

    missing = _as_bool(judgment.get("missing_information"))
    added = _as_bool(judgment.get("added_information"))
    info = 0.0 if (missing or added) else 1.0
    if missing:
        signals.append("judge: missing information")
    if added:
        signals.append("judge: added information")

    placeholder_error = _as_bool(judgment.get("placeholder_error"))
    html_error = _as_bool(judgment.get("html_error"))
    wrong_language = _as_bool(judgment.get("wrong_language"))
    placeholders = 0.0 if placeholder_error else 1.0
    html = 0.0 if html_error else 1.0
    if placeholder_error:
        signals.append("judge: placeholder error")
    if html_error:
        signals.append("judge: html error")
    if wrong_language:
        signals.append("judge: wrong language")
        semantic *= 0.2

    length = 1.0
    if max_chars and check_max_chars(translated, max_chars):
        length = 0.0
        signals.append(f"exceeds maxChars ({len(translated)} > {max_chars})")

    if _as_bool(judgment.get("grammar_error")):
        signals.append("judge: grammar error")
        fluency = min(fluency, 0.6)
    if _as_bool(judgment.get("style_error")):
        signals.append("judge: style error")

    explanation = judgment.get("explanation")
    if isinstance(explanation, str) and explanation.strip():
        signals.append(f"judge: {explanation.strip()[:120]}")
    suggestion = judgment.get("suggested_translation")
    if isinstance(suggestion, str) and suggestion.strip() and suggestion.strip() != translated.strip():
        # Kept for improve and the reviewer (C3): the judge's own fix, not applied.
        signals.append(f"{SUGGESTION_PREFIX}{suggestion.strip()[:300]}")

    dimensions = {
        "semantic": round(semantic, 3),
        "info": round(info, 3),
        "fluency": round(fluency, 3),
        "terminology": round(terminology, 3),
        "ui": round(ui, 3),
        "placeholders": round(placeholders, 3),
        "html": round(html, 3),
        "length": round(length, 3),
    }
    score = (
        _WEIGHTS["semantic"] * semantic
        + _WEIGHTS["info"] * info
        + _WEIGHTS["fluency"] * fluency
        + _WEIGHTS["terminology"] * terminology
        + _WEIGHTS["ui"] * ui
        + _WEIGHTS["placeholders"] * placeholders
        + _WEIGHTS["html"] * html
        + _WEIGHTS["length"] * length
    )
    return round(min(1.0, max(0.0, score)), 3), dimensions, signals


def judge_translation(
    provider: Provider,
    *,
    source: str,
    translated: str,
    language: str,
    model: str,
    domain: str,
    timeout_s: int,
    glossary_block: str = "",
    message_key: str = "",
    context: str = "",
    source_locale: str = "en",
    locale: str = "",
    cfg=None,
) -> JudgeResult:
    """Call the judge model; return parsed judgment or an error result."""
    prompt = build_judge_prompt(
        source=source, translated=translated, language=language, domain=domain,
        glossary_block=glossary_block, message_key=message_key, context=context,
        source_locale=source_locale, locale=locale,
    )
    try:
        raw = complete_for(cfg, provider, locale, CompletionRequest(
            prompt=prompt,
            model=model,
            schema=JUDGE_SCHEMA,
            timeout_s=timeout_s,
            options={"temperature": 0.1},
            source_texts=[source],
            target_locale=None,
        ))
    except ProviderError as exc:
        return JudgeResult(False, error=str(exc))
    return parse_judge_response(raw)


def quality_from_judge(
    *,
    source: str,
    translated: str,
    locale: str,
    glossary: dict,
    judgment: dict[str, Any],
    max_chars: int | None = None,
    standard=None,
) -> QualityResult:
    """Hard structural gate then LQS from judgment."""
    ok, reason = validate_translation(source, translated, locale, glossary, standard=standard)
    if not ok:
        return QualityResult(0.0, [reason], scorer="lqs")
    score, dimensions, signals = lqs_from_judgment(
        judgment, source=source, translated=translated, max_chars=max_chars,
    )
    return QualityResult(score, signals, dimensions=dimensions, scorer="lqs")
