"""Cross-key glossary consistency (V48, plan Part C, C2 / E9).

Per-key checks cannot see drift: a card-game app rendered "bid" as zapowiedź in 8 keys,
licytacja in 7 and oferta in 6, and each key was fine on its own. This module looks
at every key whose source uses a glossary term and records which known rendering of
the term the translation uses: the approved term (or one of its listed forms) or a
forbidden variant. A term with two or more renderings in use is a spread; the keys
using a minority rendering are the ones to fix.

Pure: callers pass ``(label, source, translation)`` rows. Matching is the V13 / V04
matcher, so inflected forms count as the same rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .validate import _contains_forbidden, _contains_morphological, _term_in_source

__all__ = ["TermSpread", "rendering_of", "term_spreads"]


@dataclass
class TermSpread:
    term: str
    locale: str
    approved: str | None
    by_rendering: dict[str, list[str]] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)

    @property
    def majority(self) -> str | None:
        """The approved term when set, else the most used rendering."""
        if self.approved:
            return self.approved
        if not self.by_rendering:
            return None
        return max(self.by_rendering, key=lambda r: len(self.by_rendering[r]))

    @property
    def outliers(self) -> dict[str, list[str]]:
        keep = self.majority
        return {r: keys for r, keys in self.by_rendering.items() if r != keep}

    def as_dict(self) -> dict:
        return {
            "term": self.term, "locale": self.locale, "approved": self.approved,
            "majority": self.majority,
            "renderings": {r: sorted(k) for r, k in self.by_rendering.items()},
            "unknown": sorted(self.unknown),
        }


def rendering_of(translated: str, data: dict, locale: str) -> str | None:
    """Which known rendering of one glossary term ``translated`` uses, if any."""
    approved = data.get(locale)
    if approved:
        forms = [str(f) for f in data.get(f"{locale}_forms") or [] if f]
        if any(_contains_morphological(translated, f, locale) for f in forms) or \
                _contains_morphological(translated, approved, locale):
            return approved
    # Renderings seen in the catalogue and tolerated, but not approved (``pl_variants``).
    for variant in data.get(f"{locale}_variants", []) or []:
        if _contains_morphological(translated, str(variant), locale):
            return str(variant)
    for bad in data.get(f"{locale}_forbidden", []) or []:
        if _contains_forbidden(translated, bad, locale):
            return bad
    return None


def term_spreads(rows, glossary: dict, locale: str) -> list[TermSpread]:
    """Every glossary term with two or more renderings across ``rows``."""
    spreads: list[TermSpread] = []
    for term, data in (glossary.get("terms") or {}).items():
        if not isinstance(data, dict):
            continue
        spread = TermSpread(term, locale, data.get(locale) or None)
        for label, source, translated in rows:
            if not translated or translated == source or not _term_in_source(term, source):
                continue
            found = rendering_of(translated, data, locale)
            if found is None:
                spread.unknown.append(label)
            else:
                spread.by_rendering.setdefault(found, []).append(label)
        if len(spread.by_rendering) >= 2 or (spread.approved and spread.outliers):
            spreads.append(spread)
    return spreads
