"""Script-family validators for unexpected alphabet / leftover Latin (V21).

Profiles are keyed by :func:`expected_script`, not one file per locale.
Foreign-script bleed is a hard gate at translate time; Latin-vs-source and
Latin-only UI are advisory (ADR-8).
"""

from __future__ import annotations

from dataclasses import dataclass

from .latin_tokens import (
    extract_identifier_spans,
    extract_prose_latin_runs,
    source_latin_allowlist,
    strip_icu_spans,
)
from .scripts import SCRIPT_RANGES as _SCRIPT_RANGES
from .scripts import char_script, expected_script

__all__ = [
    "ScriptCheckProfile",
    "profile_for_locale",
    "check_script_issues",
    "check_foreign_script",
    "foreign_script_hard_gate",
    "latin_leftover_issues",
]

_ALL_SCRIPTS = frozenset(_SCRIPT_RANGES)


@dataclass(frozen=True)
class ScriptCheckProfile:
    """Per writing-system check knobs."""

    expected: str
    foreign_scripts: frozenset[str]
    check_latin_against_source: bool
    check_latin_only_ui: bool
    latin_only_min_letters: int = 4
    foreign_min_count: int = 2


def profile_for_locale(locale: str) -> ScriptCheckProfile:
    expected = expected_script(locale)
    foreign = _ALL_SCRIPTS - {expected}
    if expected == "latin":
        return ScriptCheckProfile(
            expected=expected,
            foreign_scripts=foreign,
            check_latin_against_source=False,
            check_latin_only_ui=False,
        )
    # Latin is never "foreign" for non-Latin targets (brands / ICU) — handled
    # by latin-against-source / latin-only instead.
    foreign = foreign - {"latin"}
    return ScriptCheckProfile(
        expected=expected,
        foreign_scripts=foreign,
        check_latin_against_source=True,
        check_latin_only_ui=True,
    )


def check_foreign_script(translated: str, locale: str) -> str | None:
    """Flag letters from a script foreign to the target locale (≥2 letters).

    Latin in non-Latin locales is ignored here (see latin-against-source).
    """
    profile = profile_for_locale(locale)
    foreign_counts: dict[str, int] = {}
    for ch in translated or "":
        if not ch.isalpha():
            continue
        script = char_script(ch)
        if script is None or script == profile.expected:
            continue
        if script not in profile.foreign_scripts:
            continue
        foreign_counts[script] = foreign_counts.get(script, 0) + 1

    bad = {
        s: n for s, n in foreign_counts.items() if n >= profile.foreign_min_count
    }
    if not bad:
        return None
    parts = ", ".join(f"{n} {s}" for s, n in sorted(bad.items()))
    return f"unexpected script in {locale}: {parts}"


def foreign_script_hard_gate(translated: str, locale: str) -> str | None:
    """Translate-time hard reject — foreign script only (not Latin leftovers)."""
    return check_foreign_script(translated, locale)


def _latin_not_in_source(source: str, translated: str, locale: str) -> list[str]:
    id_allow, prose_allow = source_latin_allowlist(source)
    issues: list[str] = []

    for span in extract_identifier_spans(translated):
        if span not in id_allow:
            issues.append(
                f"latin identifier not in source ({locale}): {span!r}"
            )

    for run in extract_prose_latin_runs(translated):
        if run.casefold() not in prose_allow:
            issues.append(
                f"latin not in source ({locale}): {run!r}"
            )
    return issues


def _latin_only_ui(source: str, translated: str, locale: str) -> str | None:
    profile = profile_for_locale(locale)
    text = strip_icu_spans(translated or "")
    letters = [c for c in text if c.isalpha()]
    if len(letters) < profile.latin_only_min_letters:
        return None
    if any(char_script(c) == profile.expected for c in letters):
        return None
    # Entire string is one allowed identifier → env-var label, not leftover UI.
    stripped = text.strip()
    id_allow, _ = source_latin_allowlist(source)
    if stripped in id_allow:
        return None
    # All alpha are Latin (or unclassified Latin-range) — no expected script.
    if all(
        (s := char_script(c)) is None or s == "latin" for c in letters
    ):
        return f"latin-only for {locale} (no {profile.expected} letters)"
    return None


def latin_leftover_issues(source: str, translated: str, locale: str) -> list[str]:
    """Latin words or identifiers the source does not have, in a non-Latin translation.

    Excludes the "latin-only" case: a string that is entirely Latin is an untranslated copy of
    the source (reported as ``identical``), not a leftover inside a translation.
    """
    profile = profile_for_locale(locale)
    if not profile.check_latin_against_source or source is None:
        return []
    return _latin_not_in_source(source, translated, locale)


def check_script_issues(
    source: str, translated: str, locale: str
) -> list[str]:
    """Advisory script issues (empty if clean). Includes foreign + Latin checks."""
    profile = profile_for_locale(locale)
    issues: list[str] = []

    foreign = check_foreign_script(translated, locale)
    if foreign:
        issues.append(foreign)

    if profile.check_latin_against_source and source is not None:
        issues.extend(_latin_not_in_source(source, translated, locale))

    if profile.check_latin_only_ui and source is not None:
        only = _latin_only_ui(source, translated, locale)
        if only:
            issues.append(only)

    return issues
