"""Provider probes are parallel and soft-cached; the CLI parser is built once."""

from __future__ import annotations

import io
import json
import threading
import time

import pytest

import llm_localizator.web.settings as st_mod
from llm_localizator.projects.config import NamedProvider
from llm_localizator.web.settings import provider_status_payload

# Sleep-based and thread-timing dependent: they flake on a loaded machine, so they stay out of the fast lane.
# Not marked slow: the overlap test uses a barrier instead of a 1 s sleep (~0.1 s now).


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _cfg(make_config, tmp_path, n=3):
    providers = {
        f"p{i}": NamedProvider(id=f"p{i}", kind="ollama", url=f"http://127.0.0.1:{9000 + i}")
        for i in range(n)
    }
    return make_config(tmp_path, providers=providers)


def test_probes_run_in_parallel_and_are_cached(tmp_path, make_config, monkeypatch) -> None:
    st_mod._PROVIDER_STATUS_CACHE.clear()
    st_mod._PROVIDER_STATUS_REFRESHING.clear()
    st_mod._PROVIDER_STATUS_EVENTS.clear()
    st_mod._OLLAMA_TAGS_CACHE.clear()
    st_mod._OLLAMA_TAGS_REFRESHING.clear()
    st_mod._OLLAMA_TAGS_EVENTS.clear()
    cfg = _cfg(make_config, tmp_path)
    calls = []
    # All three probes must be in flight at once to pass the barrier: proves
    # overlap without timing a sleep (serial probes would hit BrokenBarrierError).
    barrier = threading.Barrier(3, timeout=10)

    def slow(url, timeout=None):
        calls.append(url)
        barrier.wait()
        return _Resp(json.dumps({"models": [{"name": "m"}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", slow)
    first = provider_status_payload(cfg)
    assert {v["status"] for v in first["statuses"].values()} == {"online"}
    assert len(calls) == 3
    provider_status_payload(cfg)
    assert len(calls) == 3, "second call is served from the soft cache"


def test_stale_while_revalidate_returns_cache_instantly(
    tmp_path, make_config, monkeypatch,
) -> None:
    st_mod._PROVIDER_STATUS_CACHE.clear()
    st_mod._PROVIDER_STATUS_REFRESHING.clear()
    st_mod._PROVIDER_STATUS_EVENTS.clear()
    st_mod._OLLAMA_TAGS_CACHE.clear()
    st_mod._OLLAMA_TAGS_REFRESHING.clear()
    st_mod._OLLAMA_TAGS_EVENTS.clear()
    cfg = _cfg(make_config, tmp_path, n=1)
    calls = []

    def slow(url, timeout=None):
        calls.append(url)
        time.sleep(0.05)
        return _Resp(json.dumps({"models": [{"name": f"m{len(calls)}"}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", slow)
    first = provider_status_payload(cfg)
    assert first["statuses"]["p0"]["models"] == ["m1"]
    # Age both soft caches into the stale-while-revalidate window.
    key = next(iter(st_mod._PROVIDER_STATUS_CACHE))
    stamped, payload = st_mod._PROVIDER_STATUS_CACHE[key]
    st_mod._PROVIDER_STATUS_CACHE[key] = (
        stamped - (st_mod._PROBE_SOFT_TTL_S + 1.0),
        payload,
    )
    for base, (ts, models, err) in list(st_mod._OLLAMA_TAGS_CACHE.items()):
        st_mod._OLLAMA_TAGS_CACHE[base] = (
            ts - (st_mod._PROBE_SOFT_TTL_S + 1.0), models, err,
        )
    t0 = time.perf_counter()
    second = provider_status_payload(cfg)
    assert time.perf_counter() - t0 < 0.2, "stale answer must not wait on Ollama"
    assert second["statuses"]["p0"]["models"] == ["m1"]
    # Background refresh should land a newer model list.
    for _ in range(50):
        if len(calls) >= 2:
            break
        time.sleep(0.05)
    assert len(calls) >= 2


def test_ollama_tags_shared_between_models_and_provider_status(
    tmp_path, make_config, monkeypatch,
) -> None:
    st_mod._OLLAMA_TAGS_CACHE.clear()
    st_mod._OLLAMA_TAGS_REFRESHING.clear()
    st_mod._OLLAMA_TAGS_EVENTS.clear()
    st_mod._PROVIDER_STATUS_CACHE.clear()
    calls = []

    def slow(url, timeout=None):
        calls.append(url)
        time.sleep(0.05)
        return _Resp(json.dumps({"models": [{"name": "m"}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", slow)
    models, err = st_mod.fetch_ollama_tags("http://127.0.0.1:11434")
    assert err is None and models == ["m"]
    assert len(calls) == 1
    models2, err2 = st_mod.fetch_ollama_tags("http://127.0.0.1:11434")
    assert models2 == ["m"] and err2 is None
    assert len(calls) == 1, "second /api/models hit must reuse tags cache"
    cfg = _cfg(make_config, tmp_path, n=1)
    # Point the single provider at the same host so status reuses the tags cache.
    cfg.providers["p0"] = NamedProvider(
        id="p0", kind="ollama", url="http://127.0.0.1:11434",
    )
    payload = provider_status_payload(cfg)
    assert payload["statuses"]["p0"]["status"] == "online"
    assert len(calls) == 1


def test_commands_parser_is_built_once(monkeypatch) -> None:
    import llm_localizator.web.server as srv
    import llm_localizator.web.server_logic as logic

    built = []
    real = logic.build_parser
    monkeypatch.setattr(logic, "build_parser", lambda: built.append(1) or real())
    srv._commands_manifest.cache_clear()
    srv._commands_manifest()
    srv._commands_manifest()
    assert len(built) == 1
