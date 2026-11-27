"""Localization Quality Score judge (ADR-20, ADR-158).

Asks an instruction-following model for structured dimension scores. Pure
combination math lives in :func:`lqs_from_judgment`; I/O is in
:func:`judge_translation`.

ADR-158 adds optional TransRubric-style ``issues`` (category + severity) and a
cheap per-key rubric checklist assembled from glossary / ICU / role / context —
no draft→delta→merge LLM loop.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..core.cldr import language_name
from ..core.glossary_match import glossary_hits
from ..core.icu import extract_placeholders
from ..core.quality import QualityResult
from ..core.validate import answer_leak, check_max_chars, validate_translation
from ..providers import CompletionRequest, Provider, ProviderError, complete_for

__all__ = [
    "ISSUE_CATEGORIES",
    "ISSUE_SEVERITIES",
    "JUDGE_SCHEMA",
    "JudgeResult",
    "SUGGESTION_PREFIX",
    "build_judge_prompt",
    "build_key_rubric",
    "issues_of",
    "judge_translation",
    "lqs_from_judgment",
    "normalize_issues",
    "parse_judge_response",
    "quality_from_judge",
    "suggestion_of",
]

ISSUE_CATEGORIES = frozenset({
    "instruction_following",
    "accuracy",
    "completeness",
    "terminology",
    "target_language_quality",
})

ISSUE_SEVERITIES = frozenset({"critical", "major", "minor", "trivial"})

#: Severity → hard ceiling on the composite LQS (TransRubric-inspired calibration).
_SEVERITY_CAPS = {
    "critical": 0.19,
    "major": 0.59,
    "minor": 0.89,
    "trivial": 0.99,
}

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
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "severity": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
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

#: Signal prefix for a typed issue summary (see ``issues_of`` / review-risk).
ISSUE_SIGNAL_PREFIX = "judge issue: "


def suggestion_of(signals) -> str | None:
    """The judge's suggested translation recorded in a score's signals, if any."""
    for sig in signals or []:
        if isinstance(sig, str) and sig.startswith(SUGGESTION_PREFIX):
            return sig[len(SUGGESTION_PREFIX):]
    return None


def issues_of(entry: dict | None) -> list[dict[str, str]]:
    """Typed issues from a score-sidecar row (empty when absent or malformed)."""
    if not isinstance(entry, dict):
        return []
    return normalize_issues(entry.get("issues"))


def build_key_rubric(
    *,
    source: str,
    locale: str = "",
    glossary: dict | None = None,
    message_key: str = "",
    context: str = "",
    ui_role: str = "",
    max_chars: int | None = None,
    max_width_px: float | None = None,
    font_size_px: float | None = None,
) -> list[str]:
    """Cheap per-key checklist from data we already have (ADR-158 / ADR-159).

    No LLM draft/delta/merge — concrete, verifiable checks the judge must
    PASS/FAIL against. Empty list when nothing specific applies beyond the
    generic prompt.
    """
    items: list[str] = [
        "Output must be only the target-language UI string (no explanation).",
        "Preserve every ICU/placeholder token exactly; do not translate or drop them.",
        "Cover the source meaning; do not omit or invent material facts.",
    ]
    role = (ui_role or "").strip()
    if not role and message_key:
        from .prompts import _role_from_key

        role = _role_from_key(message_key)
    if role:
        items.append(f"UI role is {role}: keep length and register suitable for that control.")
    if context and context.strip():
        items.append(f"Respect UI context: {context.strip()[:160]}")
    if max_chars is not None and max_chars > 0:
        items.append(f"Stay within {max_chars} characters (hard layout limit).")
    if max_width_px is not None:
        try:
            budget = float(max_width_px)
        except (TypeError, ValueError):
            budget = 0.0
        if budget > 0:
            from ..core.layout_qa import locale_width_factor

            fs = float(font_size_px) if font_size_px else 14.0
            if fs <= 0:
                fs = 14.0
            approx = max(1, int(budget / (0.55 * fs * locale_width_factor(locale or "en"))))
            items.append(
                f"Fit within ~{budget:.0f}px at ~{fs:.0f}px font (~{approx} chars); avoid overflow."
            )
    placeholders = extract_placeholders(source or "")
    if placeholders:
        names = ", ".join(sorted(placeholders))
        items.append(f"Required placeholders present and intact: {names}.")
    if glossary and locale:
        for hit in glossary_hits(source, glossary, locale)[:8]:
            if hit.kind == "dnt":
                items.append(f"Do-not-translate term must stay verbatim: {hit.term!r}.")
            elif hit.target:
                items.append(
                    f"Glossary: {hit.term!r} must translate as {hit.target!r}."
                )
            else:
                items.append(f"Glossary term present in source: {hit.term!r}.")
    return items


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
    rubric: list[str] | None = None,
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
    rubric_block = ""
    checks = [c.strip() for c in (rubric or []) if isinstance(c, str) and c.strip()]
    if checks:
        lines = "\n".join(f"  - {c}" for c in checks)
        rubric_block = (
            "Per-key rubric (verification checklist — not proof an error exists; "
            "accept equivalent natural paraphrases):\n"
            f"{lines}\n"
            "For each failed criterion, add an entry to \"issues\".\n\n"
        )
    return (
        f"You are a localization quality judge for {domain}.\n"
        f"Evaluate whether the {language} translation is accurate, natural, and "
        f"suitable for a product UI.\n"
        f"{gloss}{grammar}{key_line}{ctx_line}{rubric_block}"
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
        f'  "explanation": short string,\n'
        f'  "issues": optional array of '
        f'{{"category": "instruction_following|accuracy|completeness|'
        f'terminology|target_language_quality", '
        f'"severity": "critical|major|minor|trivial", '
        f'"description": "one concise English sentence"}}\n'
        f"\n"
        f"Score harshly on meaning errors. Prefer null for suggested_translation "
        f"unless you are confident in a fix that preserves ICU placeholders. "
        f"Any confirmed major issue should keep the composite quality below 60; "
        f"any minor issue below 90. Prefer an empty issues array when nothing "
        f"concrete is wrong.\n"
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


def normalize_issues(raw: Any) -> list[dict[str, str]]:
    """Validate and normalize an ``issues`` list from a judge response or sidecar."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip().lower()
        severity = str(item.get("severity") or "").strip().lower()
        description = str(item.get("description") or "").strip()
        if category not in ISSUE_CATEGORIES:
            continue
        if severity not in ISSUE_SEVERITIES:
            continue
        if not description:
            continue
        out.append({
            "category": category,
            "severity": severity,
            "description": description[:240],
        })
    return out


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


def _apply_severity_cap(score: float, issues: list[dict[str, str]]) -> float:
    if not issues:
        return score
    worst = min(
        (_SEVERITY_CAPS.get(i["severity"], 1.0) for i in issues),
        default=1.0,
    )
    return min(score, worst)


def lqs_from_judgment(
    judgment: dict[str, Any],
    *,
    source: str,
    translated: str,
    max_chars: int | None = None,
) -> tuple[float, dict[str, float], list[str], list[dict[str, str]]]:
    """Return ``(score, dimensions_0_to_1, signals, issues)`` from a parsed judgment."""
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

    issues = normalize_issues(judgment.get("issues"))
    for issue in issues:
        signals.append(
            f"{ISSUE_SIGNAL_PREFIX}{issue['severity']}/{issue['category']}: "
            f"{issue['description'][:120]}"
        )

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
    score = _apply_severity_cap(score, issues)
    return round(min(1.0, max(0.0, score)), 3), dimensions, signals, issues


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
    rubric: list[str] | None = None,
) -> JudgeResult:
    """Call the judge model; return parsed judgment or an error result."""
    prompt = build_judge_prompt(
        source=source, translated=translated, language=language, domain=domain,
        glossary_block=glossary_block, message_key=message_key, context=context,
        source_locale=source_locale, locale=locale, rubric=rubric,
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


def wrong_domain_glossary_signals(
    source: str,
    translated: str,
    locale: str,
    *,
    own_glossary: dict,
    foreign_glossary: dict,
) -> list[str]:
    """Soft signals when the translation uses a forbidden/DNT hit from another domain.

    Own-domain glossary hard-fails via :func:`validate_translation`. This catches
    cross-domain bleed (e.g. poker term in a hotel UI) without changing the judge model.
    """
    if not foreign_glossary or not source or not translated:
        return []
    from ..core.validate import glossary_violations

    own_terms = set((own_glossary.get("terms") or {}) if isinstance(own_glossary, dict) else ())
    foreign_terms = foreign_glossary.get("terms") if isinstance(foreign_glossary.get("terms"), dict) else {}
    trimmed = {
        "doNotTranslate": list(foreign_glossary.get("doNotTranslate") or []),
        "terms": {k: v for k, v in dict(foreign_terms).items() if k not in own_terms},
    }
    if not trimmed["terms"] and not trimmed["doNotTranslate"]:
        return []
    out: list[str] = []
    for hit in glossary_violations(source, translated, trimmed, locale):
        if hit.kind == "missing-approved":
            continue
        out.append(f"wrong_domain_gloss:{hit.kind}:{hit.term}")
    return out


def quality_from_judge(
    *,
    source: str,
    translated: str,
    locale: str,
    glossary: dict,
    judgment: dict[str, Any],
    max_chars: int | None = None,
    standard=None,
    foreign_glossary: dict | None = None,
) -> QualityResult:
    """Hard structural gate then LQS from judgment."""
    ok, reason = validate_translation(source, translated, locale, glossary, standard=standard)
    if not ok:
        return QualityResult(0.0, [reason], scorer="lqs")
    leak = answer_leak(source, translated)
    if leak:
        return QualityResult(0.0, [leak], scorer="lqs")
    score, dimensions, signals, issues = lqs_from_judgment(
        judgment, source=source, translated=translated, max_chars=max_chars,
    )
    if foreign_glossary:
        signals = list(signals) + wrong_domain_glossary_signals(
            source, translated, locale,
            own_glossary=glossary, foreign_glossary=foreign_glossary,
        )
    return QualityResult(
        score, signals, dimensions=dimensions, scorer="lqs", issues=issues or None,
    )
