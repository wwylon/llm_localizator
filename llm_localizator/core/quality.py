"""Automated translation quality signals (no human review required).

Scores are in ``[0, 1]``. Hard structural failures yield ``0``. Soft signals
apply multiplicative penalties. Back-translation overlap is optional so the
translate path can score cheaply and the improve path can score deeply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .latin_tokens import SCREAMING_SNAKE_RE, strip_screaming_snake
from .locale_code import base_language
from .locales import profile
from .scripts import char_script, expected_script, script_prompt_rule
from .validate import answer_leak, glossary_violations, validate_translation

__all__ = [
    "QualityResult",
    "QualityBand",
    "TOKEN_RE",
    "token_overlap",
    "check_empty_translation",
    "check_whitespace_parity",
    "expected_script",
    "script_prompt_rule",
    "check_unexpected_script",
    "check_suspicious_digraphs",
    "check_number_format",
    "score_translation",
    "quality_band",
    "is_improvement",
    "sample_consistency",
    "with_consistency",
    "LOW_CONSISTENCY",
    "char_script",
    "DEFAULT_SCORE_THRESHOLD",
    "DEFAULT_LQS_APPROVE",
    "DEFAULT_LQS_FLAG",
    "DEFAULT_LQS_RETRANSLATE",
]

DEFAULT_SCORE_THRESHOLD = 0.55
DEFAULT_LQS_APPROVE = 0.95
DEFAULT_LQS_FLAG = 0.90
DEFAULT_LQS_RETRANSLATE = 0.80

QualityBand = str  # "approve" | "flag" | "retranslate" | "needs_review" | "fail"

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
# Re-export for callers that imported the private name.
_SCREAMING_SNAKE_RE = SCREAMING_SNAKE_RE


@dataclass
class QualityResult:
    score: float
    signals: list[str] = field(default_factory=list)
    dimensions: dict[str, float] | None = None
    scorer: str = "bt"  # "bt" | "lqs" | "heuristic"
    #: Typed judge issues (ADR-158); absent for BT/heuristic and older LQS rows.
    issues: list[dict[str, str]] | None = None

    @property
    def ok(self) -> bool:
        return self.score >= DEFAULT_SCORE_THRESHOLD


def token_overlap(a: str, b: str) -> float:
    """Jaccard overlap of lowercased alphanumeric tokens."""
    ta = {t.lower() for t in TOKEN_RE.findall(strip_screaming_snake(a))}
    tb = {t.lower() for t in TOKEN_RE.findall(strip_screaming_snake(b))}
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def check_empty_translation(translated: str) -> str | None:
    if not translated or not translated.strip():
        return "empty or whitespace-only translation"
    return None


def check_whitespace_parity(source: str, translated: str) -> str | None:
    """Leading/trailing whitespace or end-punctuation mismatch."""
    if (source[:1].isspace() != translated[:1].isspace()) or (
        source[-1:].isspace() != translated[-1:].isspace()
    ):
        return "leading/trailing whitespace differs from source"
    src_end = source.rstrip()[-1:] if source.rstrip() else ""
    tr_end = translated.rstrip()[-1:] if translated.rstrip() else ""
    punct = ".!?…"
    if src_end in punct and tr_end and tr_end not in punct and not tr_end.isalnum():
        return None  # different punct style is ok
    if src_end in punct and tr_end not in punct and tr_end.isalpha():
        return f"source ends with {src_end!r} but translation does not"
    return None


# Backward-compatible private alias. The function lives in ``core.scripts``.
_char_script = char_script


def check_unexpected_script(translated: str, locale: str) -> str | None:
    """Flag letters from a script foreign to the target locale.

    Latin in non-Latin locales is ignored here (brands / ICU). Use
    :func:`llm_localizator.core.script_checks.check_script_issues` for
    latin-not-in-source and latin-only UI advisories.
    """
    from .script_checks import check_foreign_script

    return check_foreign_script(translated, locale)


def check_suspicious_digraphs(translated: str, locale: str) -> str | None:
    """Flag unlikely stacked diacritic pairs (V25).

    Latin Extended letters are valid for V21, but consecutive rare diacritics
    often indicate LLM garble rather than real Polish/German orthography.
    """
    banned = profile(locale).suspicious_digraphs
    if not banned:
        return None
    text = translated.casefold()
    found: list[str] = []
    for i in range(len(text) - 1):
        pair = text[i : i + 2]
        if pair in banned and pair not in found:
            found.append(pair)
    if not found:
        return None
    return f"suspicious digraph(s) for {locale}: {', '.join(found)}"


_GLOSSARY_FAILURE_WORDS = ("glossary", "do-not-translate", "forbidden", "approved term")


def _failed_dimensions(reason: str) -> dict[str, float]:
    """Which hard dimension a 0.0 score failed on (structural unless it names the glossary)."""
    if any(word in reason.lower() for word in _GLOSSARY_FAILURE_WORDS):
        return {"placeholder_ok": 1.0, "glossary_ok": 0.0}
    return {"placeholder_ok": 0.0}


def score_translation(
    source: str,
    translated: str,
    locale: str,
    glossary: dict | None = None,
    *,
    back_translated: str | None = None,
    max_chars: int | None = None,
    standard=None,
) -> QualityResult:
    """Compute an automated quality score for one translation."""
    glossary = glossary or {"doNotTranslate": [], "terms": {}}
    signals: list[str] = []

    empty = check_empty_translation(translated)
    if empty:
        return QualityResult(0.0, [empty], _failed_dimensions(empty), scorer="heuristic")

    ok, reason = validate_translation(source, translated, locale, glossary, standard=standard)
    if not ok:
        return QualityResult(0.0, [reason], _failed_dimensions(reason), scorer="heuristic")
    leak = answer_leak(source, translated)
    if leak:
        return QualityResult(0.0, [leak], {"placeholder_ok": 1.0}, scorer="heuristic")

    score = 1.0

    if translated.strip() == source.strip() and base_language(locale) not in (
        "en", "en-GB", "en-US",
    ):
        # Likely leftover English (V06 class). Short proper nouns are exempt
        # when identical and very short.
        if len(source.split()) >= 2 or len(source) > 12:
            score *= 0.35
            signals.append("identical to English source")

    ws = check_whitespace_parity(source, translated)
    if ws:
        score *= 0.9
        signals.append(ws)

    from .script_checks import check_script_issues

    dims: dict[str, float] = {"placeholder_ok": 1.0, "glossary_ok": 1.0, "script_ok": 1.0}

    for issue in check_script_issues(source, translated, locale):
        dims["script_ok"] = 0.0
        if "unexpected script" in issue:
            score *= 0.4
        elif "latin-only" in issue:
            score *= 0.5
        else:
            score *= 0.6  # latin not in source / identifier
        signals.append(issue)

    for issue in glossary_violations(source, translated, glossary, locale):
        if issue.blocking:
            return QualityResult(
                0.0, [issue.message], {"placeholder_ok": 1.0, "glossary_ok": 0.0},
                scorer="heuristic",
            )
        dims["glossary_ok"] = 0.0
        score *= 0.75
        signals.append(issue.message)

    if max_chars:
        dims["length_ok"] = 1.0
    if max_chars and len(translated) > max_chars:
        dims["length_ok"] = 0.0
        score *= 0.85
        signals.append(f"exceeds maxChars ({len(translated)} > {max_chars})")

    scorer = "bt" if back_translated is not None else "heuristic"
    if back_translated is not None:
        overlap = token_overlap(source, back_translated)
        dims["bt_overlap"] = round(overlap, 3)
        # Single-word UI labels rarely back-translate to the same tokens as the
        # English source; record overlap but do not crush the score.
        short_label = len(source.split()) <= 1 and len(source) <= 16
        if not short_label:
            factor = 0.4 + 0.6 * overlap
            score *= factor
        if overlap < 0.35:
            signals.append(f"low back-translation overlap ({overlap:.0%})")
        elif overlap < 0.55:
            signals.append(f"moderate back-translation overlap ({overlap:.0%})")

    return QualityResult(
        round(min(1.0, max(0.0, score)), 3), signals, dims, scorer=scorer,
    )


LOW_CONSISTENCY = 0.80


def sample_consistency(winner: str, candidates: list[str]) -> float | None:
    """How closely the other samples agree with the winner, ``0..1``.

    ``None`` when there is nothing to compare. This is the *lowest* similarity, so one
    wild sample is enough to show the model was unsure.
    """
    others = [c for c in candidates if c is not winner and c != winner]
    if not others and len(candidates) < 2:
        return None
    if not others:
        return 1.0
    from difflib import SequenceMatcher

    return round(min(SequenceMatcher(None, winner, other).ratio() for other in others), 3)


def with_consistency(result: QualityResult, consistency: float | None) -> QualityResult:
    """Record the multi-sample agreement as a dimension; a low value also raises a signal."""
    if consistency is None:
        return result
    result.dimensions = {**(result.dimensions or {}), "consistency": consistency}
    if consistency < LOW_CONSISTENCY:
        result.signals = list(result.signals) + [
            f"low-consistency: samples agree {consistency:.0%}"
        ]
    return result


_HARD_DIMENSIONS = ("placeholder_ok", "glossary_ok", "script_ok")
_DIMENSION_OK = 0.9


def is_improvement(
    new_score: float,
    new_dims: dict[str, float] | None,
    old_score: float,
    old_dims: dict[str, float] | None,
    tolerance: float = 0.02,
) -> bool:
    """Should the improve loop replace the old translation with the new one?

    A clear score win is accepted and a clear loss is not. Inside the tolerance
    the tie goes to the candidate that satisfies more dimensions, then to the
    higher score. Fixing a hard failure (placeholder, glossary, script) always
    counts. Without dimensions on both sides this is a plain ``new > old``.
    """
    if not new_dims or not old_dims:
        return new_score > old_score

    def hard_ok(dims: dict[str, float]) -> bool:
        return all(dims.get(name, 1.0) >= _DIMENSION_OK for name in _HARD_DIMENSIONS)

    new_hard, old_hard = hard_ok(new_dims), hard_ok(old_dims)
    if new_hard and not old_hard:
        return True
    if old_hard and not new_hard:
        return False

    delta = new_score - old_score
    if delta > tolerance:
        return True
    if delta < -tolerance:
        return False
    common = set(new_dims) & set(old_dims)
    new_ok = sum(1 for name in common if new_dims[name] >= _DIMENSION_OK)
    old_ok = sum(1 for name in common if old_dims[name] >= _DIMENSION_OK)
    if new_ok != old_ok:
        return new_ok > old_ok
    return new_score > old_score


def quality_band(
    score: float,
    *,
    scale: str = "bt",
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    approve: float = DEFAULT_LQS_APPROVE,
    flag: float = DEFAULT_LQS_FLAG,
    retranslate: float = DEFAULT_LQS_RETRANSLATE,
) -> str:
    """Map a score onto a decision band.

    ``scale="bt"`` keeps today's binary-ish cut (``threshold``, default 0.55):
    at/above → ``approve``, below → ``retranslate``. LQS bands (0.95/0.90/0.80)
    are available for Wave 2 when a judge is configured; do not apply them to
    BT Jaccard scores or almost every string will flag.
    """
    if score <= 0.0:
        return "fail"
    if scale == "lqs":
        if score >= approve:
            return "approve"
        if score >= flag:
            return "flag"
        if score >= retranslate:
            return "retranslate"
        return "needs_review"
    # Back-translation / heuristic scale
    if score >= threshold:
        return "approve"
    return "retranslate"


_NUMBER_RE = re.compile(
    r"(?<![\w])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+[.,]\d+)(?![\w])"
)
_DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b")


def _decimal_mark(token: str) -> str | None:
    """The decimal mark when both ``.`` and ``,`` appear. The later one wins."""
    if "," not in token or "." not in token:
        return None
    return "," if token.rfind(",") > token.rfind(".") else "."


def check_number_format(source: str, translation: str, locale: str) -> str | None:
    """V38. Opt-in. Flags a decimal-mark swap or a reordered numeric date.

    A different magnitude is not a finding. Locales outside the known comma
    and dot sets are skipped. This is not a CLDR date parser.
    """
    expected = profile(locale).decimal_mark
    if expected is None:
        return None
    source_by_digits: dict[str, str] = {}
    for token in _NUMBER_RE.findall(source):
        source_by_digits.setdefault(re.sub(r"\D", "", token), token)
    for token in _NUMBER_RE.findall(translation):
        digits = re.sub(r"\D", "", token)
        origin = source_by_digits.get(digits)
        mark = _decimal_mark(token)
        if origin is None or mark is None or mark == expected:
            continue
        return (
            f"number {token} uses {mark!r} as the decimal mark; "
            f"{locale} expects {expected!r}"
        )
    source_dates = _DATE_RE.findall(source)
    translated_dates = _DATE_RE.findall(translation)
    if len(source_dates) == 1 and len(translated_dates) == 1:
        left, right = source_dates[0], translated_dates[0]
        if left != right and sorted(left) == sorted(right):
            return (
                f"date {'/'.join(right)} reorders {'/'.join(left)}"
            )
    return None
