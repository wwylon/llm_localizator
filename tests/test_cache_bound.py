from __future__ import annotations

from llm_localizator.web.handlers_get import _CACHE_CAP, _cache_put


def test_cache_put_evicts_oldest() -> None:
    c: dict = {}
    for i in range(_CACHE_CAP + 5):
        _cache_put(c, i, i)
    assert len(c) == _CACHE_CAP
    assert 0 not in c and (_CACHE_CAP + 4) in c


def test_cache_put_refreshes_existing_key() -> None:
    c: dict = {}
    for i in range(_CACHE_CAP):
        _cache_put(c, i, i)
    _cache_put(c, 0, "new")  # now newest
    _cache_put(c, "x", 1)
    assert c[0] == "new" and 1 not in c
