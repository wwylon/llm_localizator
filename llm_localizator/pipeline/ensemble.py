"""Selective multi-model candidate policy (ADR-21)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..core.icu import extract_placeholders, extract_plural_categories
from ..core.quality import QualityResult, quality_band
from ..projects.config import LocaleRole, ProjectConfig
from .scoring import improve_score_cut

__all__ = [
    "CandidateRecord",
    "DEFAULT_HIGH_RISK_PATTERNS",
    "high_risk_source",
    "needs_secondary_pass",
    "pick_better",
    "risk_level",
]

DEFAULT_HIGH_RISK_PATTERNS: tuple[str, ...] = (
    r"\baccount\b",
    r"\bdelete\b",
    r"\bpermanently\b",
    r"\bpayment\b",
    r"\bbilling\b",
    r"\bpassword\b",
    r"\bsecurity\b",
    r"\blegal\b",
    r"\bprivacy\b",
    r"\bGDPR\b",
    r"\bunsubscribe\b",
)


@dataclass(frozen=True)
class CandidateRecord:
    text: str
    model: str
    score: float
    provider: str
    signals: list[str]


@lru_cache(maxsize=8)
def _compile_patterns(sources: tuple[str, ...]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for pat in sources:
        try:
            out.append(re.compile(pat, re.IGNORECASE))
        except re.error:
            continue
    return out


def _patterns(cfg: ProjectConfig) -> list[re.Pattern[str]]:
    raw = getattr(cfg, "high_risk_patterns", None)
    if raw is None:
        sources = DEFAULT_HIGH_RISK_PATTERNS
    else:
        sources = tuple(str(p) for p in raw if str(p).strip())
    return _compile_patterns(sources)


def high_risk_source(source: str, cfg: ProjectConfig) -> bool:
    text = source or ""
    return any(p.search(text) for p in _patterns(cfg))


def risk_level(
    source: str,
    cfg: ProjectConfig,
    *,
    html: bool = False,
    context_incomplete: bool = False,
) -> str:
    """Deterministic risk band: ``low`` | ``medium`` | ``high`` (audit A3)."""
    from ..core.icu import extract_placeholders, extract_plural_categories

    if context_incomplete and (
        high_risk_source(source, cfg) or len((source or "").split()) <= 2
    ):
        return "high"
    if high_risk_source(source, cfg):
        return "high"
    if html or extract_placeholders(source) or extract_plural_categories(source):
        return "medium"
    if len((source or "").split()) <= 2:
        return "medium"
    return "low"


def needs_secondary_pass(
    cfg: ProjectConfig,
    locale: str,
    *,
    source: str,
    translated: str,
    quality: QualityResult,
    role: LocaleRole | None = None,
) -> bool:
    """Whether to spend a secondary-model candidate for this string."""
    role = role if role is not None else cfg.role_for(locale)
    if not role.secondary:
        return False
    if role.prefer_secondary:
        return True
    if role.secondary == (role.primary or cfg.model_for(locale)):
        return False

    scale = "lqs" if quality.scorer == "lqs" else "bt"
    band = quality_band(
        quality.score,
        scale=scale,
        threshold=improve_score_cut(cfg, scorer="bt", locale=locale),
        approve=float(getattr(cfg, "band_approve", 0.95)),
        flag=float(getattr(cfg, "band_flag", 0.90)),
        retranslate=float(getattr(cfg, "band_retranslate", 0.80)),
    )
    if band in {"retranslate", "needs_review", "fail"}:
        return True
    if extract_placeholders(source) or extract_plural_categories(source) is not None:
        return True
    if high_risk_source(source, cfg):
        return True
    # V14 (expansion band) is advisory (ADR-8): never a trigger for a paid call.
    # Also when below the improve cut even if band helpers say approve (BT edge).
    if quality.score < improve_score_cut(cfg, scorer=quality.scorer, locale=locale):
        return True
    if risk_level(source, cfg, html=False) == "high":
        return True
    return False


def pick_better(
    primary: CandidateRecord,
    secondary: CandidateRecord | None,
) -> tuple[CandidateRecord, list[dict]]:
    """Return the winning candidate and a serialisable candidates list."""
    records = [primary]
    if secondary is not None:
        records.append(secondary)
    winner = primary
    if secondary is not None and secondary.score > primary.score:
        winner = secondary
    payload = [
        {"model": c.model, "score": c.score, "provider": c.provider}
        for c in records
    ]
    return winner, payload
