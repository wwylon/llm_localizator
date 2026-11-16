"""Translating between ICU plural syntax and other formats' plural models.

Everything above the catalog layer speaks ICU: validation, the prompts, the
structure signature. But most non-JSON formats do not.

    ICU          {n, plural, one {# file} other {# files}}
    gettext      msgid "# file" / msgid_plural "# files" / msgstr[0] / msgstr[1]
    Android      <plurals><item quantity="one">…</item></plurals>

So an adapter for one of those formats must convert in both directions, and the
conversion has to be lossless enough to round-trip. This module is that bridge.

The hard part is gettext, because a ``.po`` file does not name its plural forms.
It has indexed slots -- ``msgstr[0]``, ``msgstr[1]``, … -- and a ``Plural-Forms``
header giving a C expression that maps a number onto a slot index. Which CLDR
category each slot corresponds to is *convention*, not data. We recover it from
the locale's CLDR category list, which is the same source the validator uses, so
the two cannot disagree.
"""

from __future__ import annotations

import re

from .cldr import required_plural_categories
from .locales import profile
from .icu import top_level_brace_spans

__all__ = [
    "PluralSet",
    "parse_icu_plural",
    "build_icu_plural",
    "gettext_slot_order",
    "fill_catchall_categories",
    "gettext_plural_forms",
    "ANDROID_QUANTITIES",
]

# CLDR order used for gettext slot assignment. gettext indexes plural forms by
# an integer; the conventional ordering for a locale follows its CLDR category
# sequence, singular-most first.
_CLDR_ORDER = ["zero", "one", "two", "few", "many", "other"]

# Android's <item quantity="..."> uses exactly the CLDR names, so the mapping is
# the identity -- but it accepts only these six and nothing else.
ANDROID_QUANTITIES = set(_CLDR_ORDER)

def gettext_plural_forms(locale: str) -> str | None:
    """The ``Plural-Forms`` header emitted when writing a .po from scratch.

    An existing header in a file always wins over this.
    """
    return profile(locale).gettext_plural_forms


_NPLURALS_RE = re.compile(r"nplurals\s*=\s*(\d+)")
PLURAL_HEAD_RE = re.compile(
    r"^\s*(\w+)\s*,\s*(plural|selectordinal)\s*,\s*(.*)$", re.DOTALL,
)


class PluralSet:
    """A parsed ICU plural clause: the driving variable plus its branches.

    ``branches`` maps a selector to its text. Selectors are CLDR category names
    (``one``) or explicit values (``=0``); the distinction is preserved so a
    round-trip does not silently rewrite ``=0`` into ``zero``, which means
    something different.
    """

    __slots__ = ("variable", "branches", "prefix", "suffix", "keyword")

    def __init__(self, variable: str, branches: dict[str, str],
                 prefix: str = "", suffix: str = "", keyword: str = "plural") -> None:
        if keyword not in ("plural", "selectordinal"):
            raise ValueError(f"plural keyword must be plural or selectordinal, got {keyword!r}")
        self.variable = variable
        self.branches = branches
        self.prefix = prefix
        self.suffix = suffix
        self.keyword = keyword

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, PluralSet)
                and (self.variable, self.branches, self.prefix, self.suffix, self.keyword)
                == (other.variable, other.branches, other.prefix, other.suffix, other.keyword))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PluralSet({self.variable!r}, {self.branches!r})"

    def categories(self) -> set[str]:
        return set(self.branches)

    def ordered(self, categories: list[str]) -> list[str]:
        """Branch texts in the order given, falling back to ``other`` then ``""``."""
        fallback = self.branches.get("other", "")
        return [self.branches.get(c, fallback) for c in categories]


def _arms(body: str) -> list[tuple[str, str]]:
    """Selector/body pairs inside a plural or select clause. Brace-depth aware.

    Handles both word selectors (``one``, ``other``) and numeric selectors
    (``=0``, ``=1``). Used by :func:`_split_branches` and ``render/icu``.
    """
    arms: list[tuple[str, str]] = []
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        if body[i] == "=":
            i += 1
            while i < n and body[i].isdigit():
                i += 1
        else:
            while i < n and (body[i].isalnum() or body[i] == "_"):
                i += 1
        selector = body[start:i]
        if not selector:
            break
        while i < n and body[i].isspace():
            i += 1
        if i >= n or body[i] != "{":
            break
        depth = 0
        end = i
        while end < n:
            if body[end] == "{":
                depth += 1
            elif body[end] == "}":
                depth -= 1
                if depth == 0:
                    arms.append((selector, body[i + 1 : end]))
                    i = end + 1
                    break
            end += 1
        else:
            break
    return arms


def _split_branches(body: str) -> dict[str, str]:
    """Parse ``one {a} other {b}`` into ``{"one": "a", "other": "b"}``.

    Delegates to :func:`_arms` for the brace-aware parse.
    """
    return dict(_arms(body))


def parse_icu_plural(text: str) -> PluralSet | None:
    """Parse an ICU plural message, or return ``None`` if it is not one.

    Text before and after the clause is preserved so ``build_icu_plural`` can
    reconstruct the original exactly.
    """
    for span in top_level_brace_spans(text):
        m = PLURAL_HEAD_RE.match(span[1:-1])
        if not m:
            continue
        idx = text.index(span)
        branches = _split_branches(m.group(3))
        if not branches:
            return None
        return PluralSet(m.group(1), branches,
                         prefix=text[:idx], suffix=text[idx + len(span):],
                         keyword=m.group(2))
    return None


def build_icu_plural(plural: PluralSet) -> str:
    """Inverse of :func:`parse_icu_plural`.

    Branches are emitted in CLDR order with explicit-value selectors first,
    which is how ICU examples are conventionally written and keeps output stable
    regardless of dict insertion order.
    """
    explicit = sorted(k for k in plural.branches if k.startswith("="))
    named = [c for c in _CLDR_ORDER if c in plural.branches]
    unknown = sorted(set(plural.branches) - set(explicit) - set(named))
    parts = [f"{k} {{{plural.branches[k]}}}" for k in [*explicit, *named, *unknown]]
    return f"{plural.prefix}{{{plural.variable}, {plural.keyword}, {' '.join(parts)}}}{plural.suffix}"


def gettext_slot_order(locale: str, nplurals: int | None = None) -> list[str]:
    """CLDR categories in gettext ``msgstr[N]`` slot order for ``locale``.

    A ``.po`` file numbers its plural forms rather than naming them, so the slot
    to category mapping is convention. We take the locale's CLDR categories in
    singular-most-first order, which matches how gettext catalogues for these
    languages are conventionally written.

    ``nplurals`` from the file's own header wins when it disagrees with our CLDR
    table -- the file is the authority on its own shape. A shorter list is
    truncated; a longer one is extended with synthetic ``other_2``, ``other_3``,
    … keys so that every gettext slot maps to a distinct ICU category name and
    no plural form is silently lost.
    """
    categories = list(profile(locale).plural_categories)
    order = [c for c in _CLDR_ORDER if c in categories]
    if nplurals is None:
        return order
    if len(order) > nplurals:
        return order[:nplurals]
    extras = [f"other_{j}" for j in range(2, nplurals - len(order) + 2)]
    return order + extras


def fill_catchall_categories(branches: dict[str, str], locale: str) -> dict[str, str]:
    """Complete a branch set using the catch-all slot for missing categories.

    gettext and CLDR do not always agree on how many forms a language has, and
    gettext usually has fewer. Polish is the standard example: CLDR requires
    ``one/few/many/other``, but Polish ``.po`` files declare ``nplurals=3``.
    The missing category is ``other``, which for Polish covers fractional
    quantities ("1.5 lewy") that gettext's integer-only plural expression has no
    way to select.

    So a plural read back out of a ``.po`` would be missing a category the
    validator requires, and every counted noun in the catalogue would fail
    validation through no fault of the translation.

    The fix is to copy the **last** slot -- gettext's catch-all, the branch its
    expression falls through to -- into any required category that has no slot
    of its own. That is what a human filling in the ICU form would write, and it
    is what the gettext file actually means.

    Round-tripping is therefore lossy in one direction: ICU -> po -> ICU may
    collapse a distinct ``other`` into the catch-all text. That is a limit of
    the format, not something an adapter can fix.
    """
    if not branches:
        return branches
    required = required_plural_categories(locale)
    present = {k for k in branches if not k.startswith("=")}
    missing = required - present
    if not missing:
        return branches

    catchall = next(
        (branches[c] for c in reversed(_CLDR_ORDER) if c in branches),
        next(iter(branches.values())),
    )
    return {**branches, **{c: catchall for c in missing}}


def nplurals_from_header(plural_forms: str | None) -> int | None:
    """Read ``nplurals=N`` out of a gettext ``Plural-Forms`` header."""
    if not plural_forms:
        return None
    m = _NPLURALS_RE.search(plural_forms)
    return int(m.group(1)) if m else None


def icu_placeholder_to_printf(text: str, variable: str) -> str:
    """Rewrite ICU ``#`` and ``{var}`` into gettext-friendly ``%(var)s``.

    gettext has no ``#`` concept; Python-style named interpolation is the
    convention that survives round-tripping and is what most tooling expects.
    """
    return text.replace("#", f"%({variable})s")


def printf_placeholder_to_icu(text: str, variable: str) -> str:
    """Inverse of :func:`icu_placeholder_to_printf`."""
    return text.replace(f"%({variable})s", "#")
