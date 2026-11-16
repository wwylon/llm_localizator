"""Human-language matrix: every language is found as reliably as English (see human_spec.py).

A phrase counts when it is reported at medium or high confidence. The only absolute exceptions are listed
in ``NOT_BY_DESIGN``: hosts where the English phrase is not reported either.
"""

from __future__ import annotations

import pytest

from .human_runner import run_host
from .human_spec import HOSTS, KINDS, LANGS

#: (host, kind): English is not reported there on purpose (a lone word after ``echo`` may be a name).
NOT_BY_DESIGN = {("php", "label")}
_CACHE: dict[str, dict] = {}


def _cells(host: str) -> dict:
    if host not in _CACHE:
        _CACHE[host] = run_host(host)
    return _CACHE[host]


@pytest.mark.parametrize("host", sorted(HOSTS))
def test_every_language_is_found_like_english(host: str) -> None:
    cells = _cells(host)
    missing = [
        f"{lang}/{kind}" for lang, kinds in cells.items() for kind in KINDS
        if not kinds[kind] and (host, kind) not in NOT_BY_DESIGN
    ]
    assert not missing, f"{host}: not reported for {missing}"


def test_languages_cover_the_writing_system_groups() -> None:
    groups = {group for group, _ in LANGS.values()}
    assert {"latin-diacritics", "rtl-abjad", "indic-abugida", "cjk", "sea-unsegmented", "ethiopic"} <= groups


@pytest.mark.parametrize("host", sorted(__import__("tests.scan.matrix.human_spec", fromlist=["NEGATIVE_HOSTS"]).NEGATIVE_HOSTS))
def test_developer_text_in_any_language_stays_silent(host: str) -> None:
    from .human_runner import run_negative

    assert run_negative(host) == [], f"{host}: developer-only text reported"


@pytest.mark.parametrize("host", ["js", "python", "kotlin", "swift", "html"])
def test_language_peculiarities(host: str) -> None:
    """Interpolation next to native text, mixed Latin tokens, native digits, decomposed Unicode, one-ideograph labels."""
    from .human_runner import run_extra

    assert run_extra(host) == {}, f"{host}: not reported {run_extra(host)}"
