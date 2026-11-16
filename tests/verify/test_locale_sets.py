"""Hermetic checks for every locale in the verify sets: profile lookup never fails,
plural categories are valid CLDR names, and unprofiled languages fall back safely."""

import pytest

from llm_localizator.core.locales import profile
from llm_localizator.core.locales.base import CLDR_CATEGORIES
from llm_localizator.verify.locale_sets import LOCALE_SETS, resolve_locales

_ALL = sorted({c for codes in LOCALE_SETS.values() for c in codes})


@pytest.mark.parametrize("code", _ALL)
def test_profile_lookup_is_total_and_valid(code):
    p = profile(code)
    assert set(p.plural_categories) <= CLDR_CATEGORIES
    assert "other" in p.plural_categories
    assert p.direction in ("ltr", "rtl")


@pytest.mark.parametrize("code", LOCALE_SETS["rtl"][:5])
def test_rtl_set_profiles_are_rtl(code):
    assert profile(code).direction == "rtl"


def test_resolve_expands_sets_and_dedupes():
    out = resolve_locales("plurals, de,pl")
    assert out[:2] == ["pl", "ru"] and out.count("pl") == 1 and "de" in out
    assert resolve_locales(None) == []


def test_s9_lists_unprofiled_locales(tmp_path):
    from llm_localizator.verify.runner import Ctx, UNSUPPORTED
    from llm_localizator.verify.stages import s9_locale_robustness

    ctx = Ctx(tmp_path, tmp_path, tmp_path, "deep", "unprofiled")
    res = s9_locale_robustness(ctx)
    assert res.verdict in ("pass", UNSUPPORTED)
    assert isinstance(res.metrics["unprofiled"], list)
