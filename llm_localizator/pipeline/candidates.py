"""Shared candidate acceptance policy for model-generated translations."""

from __future__ import annotations

from ..core.normalize import normalize_candidate
from ..core.script_checks import check_script_issues, foreign_script_hard_gate
from ..core.validate import (
    check_agent_artifacts,
    check_untranslated_fragments,
    glossary_violations,
    validate_translation,
)
from .frame_samples import restore_frame_values
from .placeholder_mask import restore_placeholders

__all__ = ["validate_candidate", "accept_candidate", "soft_issues"]


def validate_candidate(
    source: str, candidate: str | None, locale: str, glossary: dict,
    *, placeholder_mask: dict[str, str] | None = None,
    check_html: bool | None = None,
    standard=None,
    applied: list[str] | None = None,
    frame_samples: dict[str, str] | None = None,
    prompt_text: str | None = None,
) -> tuple[str | None, str | None]:
    """Normalize and validate one provider result.

    The pipeline stages use the same hard gates: structural/glossary validation
    followed by foreign-script validation. ``None`` is returned with a
    human-readable reason when the candidate must be discarded.
    """
    text = restore_placeholders((candidate or "").strip(), placeholder_mask)
    # A frame shown with sample values (ADR-124) may come back with a value where
    # its placeholder belongs; put the placeholder back when that is unambiguous.
    text = restore_frame_values(text, frame_samples)
    # Quotes, "..." and first-letter case have one right answer given the source:
    # fix them here instead of rejecting and retrying (C2). ``applied`` collects
    # the step names for the caller's report.
    text, steps = normalize_candidate(source, text, locale)
    if applied is not None:
        applied.extend(steps)
    ok, reason = validate_translation(
        source, text, locale, glossary, check_html=check_html, standard=standard,
        prompt_text=prompt_text,
    )
    if not ok:
        return None, reason
    # Belt-and-braces: validate_translation already rejects these; soft_issues
    # also surface them so retries can clear residual trailers.
    artifact = check_agent_artifacts(source, text)
    if artifact:
        return None, artifact
    script_issue = foreign_script_hard_gate(text, locale)
    if script_issue:
        return None, script_issue
    return text, None


def soft_issues(source: str, text: str, locale: str, glossary: dict) -> list[str]:
    """Defects an accepted translation may still carry: advisory by design (ADR-8).

    Latin words that the source does not have in a non-Latin locale, English stopwords in a
    Latin one, the source echoed back, and an approved glossary term that is missing. The
    translate loop retries once on these and keeps the retry only when it is better; nothing
    here rejects.
    """
    issues: list[str] = []
    for issue in check_script_issues(source, text, locale):
        if issue.startswith("latin"):
            issues.append(issue)
    fragments = check_untranslated_fragments(text, locale)
    if fragments:
        issues.append(fragments)
    words = source.split()
    if text.strip() == source.strip() and len(words) >= 2 and any(ch.isalpha() for ch in source):
        issues.append("identical to the source: translate it")
    for problem in glossary_violations(source, text, glossary, locale):
        if not problem.blocking:
            issues.append(problem.message)
    return issues


def accept_candidate(
    source: str, candidate: str | None, locale: str, glossary: dict,
    *, placeholder_mask: dict[str, str] | None = None,
    check_html: bool | None = None,
    standard=None,
    applied: list[str] | None = None,
    frame_samples: dict[str, str] | None = None,
    prompt_text: str | None = None,
) -> tuple[str | None, str | None]:
    """Sole acceptance gate for generate / shorten / refine / secondary / import.

    Alias of :func:`validate_candidate` — kept as the audit A1 name so call
    sites and docs share one vocabulary.
    """
    return validate_candidate(
        source, candidate, locale, glossary,
        placeholder_mask=placeholder_mask, check_html=check_html,
        standard=standard, applied=applied, frame_samples=frame_samples,
        prompt_text=prompt_text,
    )
