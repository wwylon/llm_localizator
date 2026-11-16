"""Every language answers the same questions (see spec.py). Gaps are listed in known_gaps.py."""

from __future__ import annotations

import pytest

from .known_gaps import KNOWN_GAPS
from .runner import run_language, run_reported_only
from .spec import LANGS, REPORTED_ONLY

_CACHE: dict[str, dict] = {}


def _cells(lang: str) -> dict:
    if lang not in _CACHE:
        _CACHE[lang] = run_language(lang)
    return _CACHE[lang]


def _params():
    for lang, (_name, snippets) in LANGS.items():
        for cat in snippets:
            marks = [pytest.mark.xfail(strict=True, reason="known matrix gap")] if (lang, cat) in KNOWN_GAPS else []
            yield pytest.param(lang, cat, id=f"{lang}-{cat}", marks=marks)


@pytest.mark.parametrize(("lang", "cat"), list(_params()))
def test_cell(lang: str, cat: str) -> None:
    cell = _cells(lang)[cat]
    assert cell["ok"], f"{lang}/{cat}: intent={cell['intent']} found={cell['found']}"


@pytest.mark.parametrize("lang", sorted(REPORTED_ONLY))
def test_languages_without_a_scanner_are_reported(lang: str) -> None:
    assert run_reported_only(lang), f"{lang}: file type is silently skipped"
