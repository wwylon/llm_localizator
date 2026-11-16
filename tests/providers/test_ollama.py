"""Ollama payload construction (hermetic -- no live server)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from llm_localizator.providers import CompletionRequest, OllamaProvider, ProviderError
from llm_localizator.providers import ollama as ollama_mod


@pytest.fixture(autouse=True)
def _clear_tags_cache() -> None:
    ollama_mod._tags_cache.clear()


def _ndjson_response(*chunks: dict) -> object:
    lines = [json.dumps(c).encode("utf-8") + b"\n" for c in chunks]

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def readline(self):
            if not lines:
                return b""
            return lines.pop(0)

    return _Response()


def _fake_urlopen(captured: dict, response: object | None = None):
    def _open(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        captured["timeout"] = timeout
        if response is not None:
            return response
        return _ndjson_response({"response": "ok", "done": True})

    return _open


def test_payload_omits_images_when_absent() -> None:
    captured: dict = {}
    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen(captured)):
        provider.complete(CompletionRequest(prompt="hi", model="testmodel"))
    assert captured["payload"]["stream"] is True
    assert "images" not in captured["payload"]


def test_payload_prepends_system_for_generate_api() -> None:
    """ADR-111 splits system/user; /api/generate has no system field."""
    captured: dict = {}
    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen(captured)):
        provider.complete(CompletionRequest(
            prompt="String to translate:\nSave",
            system="Output ONLY the translated UI text.\n",
            model="aya-expanse:8b",
        ))
    assert captured["payload"]["prompt"] == (
        "Output ONLY the translated UI text.\n"
        "String to translate:\nSave"
    )


def test_payload_leaves_prompt_alone_when_system_empty() -> None:
    captured: dict = {}
    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen(captured)):
        provider.complete(CompletionRequest(prompt="hi", system="  ", model="m"))
    assert captured["payload"]["prompt"] == "hi"


def test_payload_includes_images_when_present() -> None:
    captured: dict = {}
    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen(captured)):
        provider.complete(CompletionRequest(
            prompt="hi", model="llava", images=["ZmFrZQ=="],
        ))
    assert captured["payload"]["images"] == ["ZmFrZQ=="]


def test_streaming_concatenates_chunks() -> None:
    captured: dict = {}
    chunks = _ndjson_response(
        {"response": "hel", "done": False},
        {"response": "lo", "done": True},
    )
    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen(captured, chunks)):
        text = provider.complete(CompletionRequest(prompt="hi", model="testmodel"))
    assert text == "hello"


def _req_url(req) -> str:
    """``urlopen`` may receive a URL string (tags) or a ``Request`` (generate)."""
    if isinstance(req, str):
        return req
    return getattr(req, "full_url", None) or req.get_full_url()


def test_timeout_raises_provider_error() -> None:
    def _open(req, timeout=None):
        raise TimeoutError("timed out")

    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=_open):
        with pytest.raises(ProviderError, match="timed out"):
            provider.complete(CompletionRequest(prompt="hi", model="m", timeout_s=1))


def test_http_404_is_model_not_found_not_unreachable() -> None:
    """Missing model must not be misreported as daemon down."""
    import urllib.error

    def _open(req, timeout=None):
        raise urllib.error.HTTPError(
            url="http://localhost:11434/api/generate",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=_open):
        with pytest.raises(ProviderError, match="not found.*ollama pull"):
            provider.complete(CompletionRequest(prompt="hi", model="missing:99b"))


def _tags_response(models: list[str]):
    class _Tags:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            body = {"models": [{"name": name} for name in models]}
            return json.dumps(body).encode("utf-8")

    return _Tags()


def test_ensure_ready_fails_fast_when_model_not_installed() -> None:
    provider = OllamaProvider()
    calls: list[str] = []

    def _open(req, timeout=None):
        url = _req_url(req)
        calls.append(url)
        if url.endswith("/api/tags"):
            return _tags_response(["aya-expanse:8b", "qwen2.5:7b"])
        raise AssertionError("generate should not run when model is absent")

    with patch("urllib.request.urlopen", side_effect=_open):
        with pytest.raises(ProviderError, match="not installed.*qwen2.5:7b"):
            provider.ensure_ready("qwen2.5:14b")
    assert all("/api/generate" not in u for u in calls)


def test_ensure_ready_accepts_bare_name_matching_latest_tag() -> None:
    provider = OllamaProvider()
    captured: dict = {}

    def _open(req, timeout=None):
        url = _req_url(req)
        if url.endswith("/api/tags"):
            return _tags_response(["llama3.2:latest"])
        return _fake_urlopen(captured)(req, timeout)

    with patch("urllib.request.urlopen", side_effect=_open):
        provider.ensure_ready("llama3.2")
    assert captured["payload"]["model"] == "llama3.2"


def test_ensure_ready_fails_when_tags_unreachable() -> None:
    provider = OllamaProvider(url="http://localhost:59999")

    def _open(req, timeout=None):
        raise OSError("connection refused")

    with patch("urllib.request.urlopen", side_effect=_open):
        with pytest.raises(ProviderError, match="not reachable"):
            provider.ensure_ready("testmodel")


def test_ensure_ready_retries_generate_until_ok() -> None:
    """Tags can succeed while the first generate still fails after unload."""
    provider = OllamaProvider()
    calls: list[str] = []
    generate_failures_left = 2

    def _open(req, timeout=None):
        url = _req_url(req)
        if url.endswith("/api/tags"):
            calls.append("tags")

            class _Tags:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self):
                    return b'{"models":[]}'

            return _Tags()
        calls.append("generate")
        nonlocal generate_failures_left
        if generate_failures_left > 0:
            generate_failures_left -= 1
            raise TimeoutError("loading")
        return _ndjson_response({"response": "OK", "done": True})

    reports: list[str] = []
    with (
        patch("urllib.request.urlopen", side_effect=_open),
        patch("llm_localizator.providers.ollama.time.sleep"),
    ):
        provider.ensure_ready("testmodel", report=reports.append)

    # One /api/tags probe, then generate retries.
    assert calls.count("tags") == 1
    assert calls.count("generate") == 3
    assert any("warming up" in line for line in reports)
    assert any("attempt 1/" in line for line in reports)


def test_ensure_ready_raises_after_exhausted_retries() -> None:
    provider = OllamaProvider()

    def _open(req, timeout=None):
        url = _req_url(req)
        if url.endswith("/api/tags"):
            class _Tags:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self):
                    return b'{"models":[]}'

            return _Tags()
        raise TimeoutError("still loading")

    with (
        patch("urllib.request.urlopen", side_effect=_open),
        patch("llm_localizator.providers.ollama.time.sleep"),
    ):
        with pytest.raises(ProviderError, match="not ready after"):
            provider.ensure_ready("testmodel")


def test_ensure_ready_warmup_caps_num_predict() -> None:
    captured: dict = {}
    provider = OllamaProvider()

    def _open(req, timeout=None):
        url = _req_url(req)
        if url.endswith("/api/tags"):
            class _Tags:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self):
                    return b'{"models":[]}'

            return _Tags()
        return _fake_urlopen(captured)(req, timeout)

    with patch("urllib.request.urlopen", side_effect=_open):
        provider.ensure_ready("testmodel")
    assert captured["payload"]["options"]["num_predict"] == 8
    assert captured["payload"]["model"] == "testmodel"


def test_malformed_tags_payload_raises_provider_error() -> None:
    from llm_localizator.providers.ollama import _tags_cache

    provider = OllamaProvider()
    _tags_cache.clear()

    class _Tags:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'[]'

    with patch("urllib.request.urlopen", return_value=_Tags()):
        with pytest.raises(ProviderError, match="non-object"):
            provider._load_tags()
    # available_models swallows ProviderError
    with patch("urllib.request.urlopen", return_value=_Tags()):
        assert provider.available_models() == []


def test_available_models_reuses_tags_for_thirty_seconds() -> None:
    provider = OllamaProvider()
    calls = {"n": 0}

    def _open(req, timeout=None):
        calls["n"] += 1

        class _Tags:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"models":[{"name":"llama3.2"}]}'

        return _Tags()

    with patch("urllib.request.urlopen", side_effect=_open):
        assert provider.available_models() == ["llama3.2"]
        assert provider.available_models() == ["llama3.2"]
    assert calls["n"] == 1


def test_error_chunk_is_not_an_empty_response() -> None:
    provider = OllamaProvider()
    response = _ndjson_response({"error": "model failed to load"})
    with patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(ProviderError, match="model failed to load"):
            provider.complete(CompletionRequest(prompt="hi", model="testmodel"))


def test_error_after_partial_text_is_not_returned() -> None:
    provider = OllamaProvider()
    response = _ndjson_response(
        {"response": "half"},
        {"error": "boom", "done": True},
    )
    with patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(ProviderError, match="boom"):
            provider.complete(CompletionRequest(prompt="hi", model="testmodel"))


@pytest.mark.parametrize(("raw", "expected"), [
    ("</think>\n\nZapisz", "Zapisz"),
    ("<think>\nreasoning\n</think>\n\nZapisz", "Zapisz"),
    ("<think>\n\n</think>\n\nZapisz", "Zapisz"),
    ("Zapisz", "Zapisz"),
    ("Zapisz </think> tak", "Zapisz </think> tak"),
    ("<think>never closed", "<think>never closed"),
])
def test_leading_think_is_stripped(raw: str, expected: str) -> None:
    provider = OllamaProvider()
    response = _ndjson_response({"response": raw, "done": True})
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen({}, response)):
        assert provider.complete(CompletionRequest(prompt="hi", model="m")) == expected


def test_think_only_reply_is_empty_error() -> None:
    provider = OllamaProvider()
    response = _ndjson_response({"response": "</think>\n\n", "done": True})
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen({}, response)):
        with pytest.raises(ProviderError, match="empty"):
            provider.complete(CompletionRequest(prompt="hi", model="m"))
