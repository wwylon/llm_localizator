"""Hermetic tests for Anthropic and DeepL providers (mocked HTTP)."""

from __future__ import annotations

import json

import pytest

from llm_localizator.providers import build_provider
from llm_localizator.providers.anthropic import AnthropicProvider
from llm_localizator.providers.base import CompletionRequest, ProviderError
from llm_localizator.providers.deepl import DeepLProvider
from llm_localizator.providers._prompt_utils import extract_sources as _extract_sources
from llm_localizator.projects.config import ProviderConfig


class _FakeResp:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_build_provider_anthropic_and_deepl() -> None:
    assert isinstance(build_provider(ProviderConfig(kind="anthropic")), AnthropicProvider)
    assert isinstance(build_provider(ProviderConfig(kind="deepl")), DeepLProvider)


def test_anthropic_missing_key_raises(monkeypatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "LLM_LOCALIZATOR_ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    p = AnthropicProvider(api_key="")
    with pytest.raises(ProviderError, match="API key"):
        p.complete(CompletionRequest(prompt="hi", model="claude-haiku-4-5"))


def test_anthropic_parses_content(monkeypatch) -> None:
    def fake_urlopen(req, timeout=0):
        return _FakeResp({
            "content": [{"type": "text", "text": "Cześć"}],
        })

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    p = AnthropicProvider(api_key="test-key")
    assert p.complete(CompletionRequest(prompt="Translate Hello", model="x")) == "Cześć"


def test_anthropic_default_is_haiku_5_5() -> None:
    from llm_localizator.providers.anthropic import DEFAULT_MODEL
    from llm_localizator.catalog.pricing import CLOUD_DEFAULT_MODEL

    assert DEFAULT_MODEL == "claude-haiku-5-5"
    assert CLOUD_DEFAULT_MODEL["anthropic"] == "claude-haiku-5-5"


def test_anthropic_sends_system_cache_control(monkeypatch) -> None:
    seen = {}

    def fake_urlopen_json(req, timeout, kind):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["headers"] = dict(req.headers)
        return {
            "content": [{"type": "text", "text": '["ok"]'}],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_input_tokens": 100,
            },
        }

    monkeypatch.setattr(
        "llm_localizator.providers.anthropic.urlopen_json", fake_urlopen_json,
    )
    p = AnthropicProvider(api_key="test-key")
    out = p.complete(CompletionRequest(
        prompt="Strings:\n1. Hi",
        system="You are a translator.\n",
        model="claude-haiku-5-5",
        schema={"type": "array", "items": {"type": "string"}},
    ))
    assert out == '["ok"]'
    system = seen["body"]["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"]["type"] == "ephemeral"
    assert system[0]["cache_control"]["ttl"] == "5m"
    assert p.last_usage["cache_read_input_tokens"] == 100


def test_anthropic_complete_many_message_batches(monkeypatch, capsys) -> None:
    calls = {"create": 0, "status": 0, "results": 0}

    def fake_urlopen_json(req, timeout, kind):
        url = getattr(req, "full_url", None) or req.get_full_url()
        if url.endswith("/messages/batches") and req.get_method() == "POST":
            calls["create"] += 1
            body = json.loads(req.data.decode("utf-8"))
            assert len(body["requests"]) == 2
            assert body["requests"][0]["params"]["system"][0]["cache_control"]["ttl"] == "1h"
            return {"id": "msgbatch_test"}
        if url.endswith("/messages/batches/msgbatch_test"):
            calls["status"] += 1
            return {"processing_status": "ended", "id": "msgbatch_test"}
        raise AssertionError(f"unexpected urlopen_json url {url}")

    class _ResultsResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            calls["results"] += 1
            lines = []
            for cid, text in (("a", '["A"]'), ("b", '["B"]')):
                lines.append(json.dumps({
                    "custom_id": cid,
                    "result": {
                        "type": "succeeded",
                        "message": {
                            "content": [{"type": "text", "text": text}],
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        },
                    },
                }))
            return ("\n".join(lines) + "\n").encode("utf-8")

    def fake_urlopen(req, timeout=0):
        url = getattr(req, "full_url", None) or req.get_full_url()
        assert url.endswith("/results")
        return _ResultsResp()

    monkeypatch.setattr(
        "llm_localizator.providers.anthropic.urlopen_json", fake_urlopen_json,
    )
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    p = AnthropicProvider(api_key="test-key")
    out = p.complete_many([
        CompletionRequest(
            prompt="1. a", system="sys", model="claude-haiku-5-5", custom_id="a",
        ),
        CompletionRequest(
            prompt="1. b", system="sys", model="claude-haiku-5-5", custom_id="b",
        ),
    ])
    assert out == ['["A"]', '["B"]']
    assert calls["create"] == 1 and calls["status"] >= 1 and calls["results"] == 1
    err = capsys.readouterr().err
    assert "submitted" in err and "asynchronously" in err and "ended after" in err
    assert "test-key" not in err


def test_openai_compat_meters_cached_tokens(monkeypatch) -> None:
    from llm_localizator.providers.openai_compat import OpenAICompatibleProvider

    def fake_urlopen_json(req, timeout, kind):
        body = json.loads(req.data.decode("utf-8"))
        assert body["messages"][0]["role"] == "system"
        assert body["thinking"]["type"] == "disabled"
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": '["x"]'},
            }],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 5,
                "prompt_cache_hit_tokens": 800,
                "prompt_cache_miss_tokens": 200,
            },
        }

    monkeypatch.setattr(
        "llm_localizator.providers.openai_compat.urlopen_json", fake_urlopen_json,
    )
    p = OpenAICompatibleProvider(
        kind="deepseek",
        api_key="k",
        env_var="DEEPSEEK_API_KEY",
        url="https://api.deepseek.com/chat/completions",
        default_model="deepseek-flash",
        disable_thinking=True,
    )
    assert p.complete(CompletionRequest(
        prompt="user", system="stable prefix", model="deepseek-flash",
    )) == '["x"]'
    assert p.last_usage["prompt_cache_hit_tokens"] == 800


def test_openai_compat_rejects_length_finish_reason(monkeypatch) -> None:
    from llm_localizator.providers.openai_compat import OpenAICompatibleProvider

    def fake_urlopen_json(req, timeout, kind):
        return {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": "truncated…"},
            }],
        }

    monkeypatch.setattr(
        "llm_localizator.providers.openai_compat.urlopen_json", fake_urlopen_json,
    )
    p = OpenAICompatibleProvider(
        kind="openai",
        api_key="test-key",
        env_var="OPENAI_API_KEY",
        url="https://api.openai.com/v1/chat/completions",
        default_model="gpt-4o-mini",
    )
    with pytest.raises(ProviderError, match="token limit"):
        p.complete(CompletionRequest(prompt="hi", model="gpt-4o-mini"))


def test_anthropic_rejects_max_tokens_stop(monkeypatch) -> None:
    monkeypatch.setattr(
        "llm_localizator.providers.anthropic.urlopen_json",
        lambda req, timeout, kind: {
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": "cut o"}],
            "usage": {"input_tokens": 5, "output_tokens": 9},
        },
    )
    p = AnthropicProvider(api_key="test-key")
    with pytest.raises(ProviderError, match="token limit"):
        p.complete(CompletionRequest(prompt="hi", model="claude-haiku-4-5"))
    assert p.last_usage == {"input_tokens": 5, "output_tokens": 9}  # still billable


def test_deepl_extracts_single_and_batch() -> None:
    single = "Rules:\n\nString to translate:\nHello"
    assert _extract_sources(single, None) == ["Hello"]
    batch = (
        "Examples\n\nStrings to translate:\n"
        "1. Hello\n"
        "2. Bye  [context: x]\n\n"
        "JSON array"
    )
    assert _extract_sources(batch, {"minItems": 2}) == ["Hello", "Bye"]


def test_deepl_translates_via_form(monkeypatch) -> None:
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        body = req.data.decode("utf-8")
        seen["body"] = body
        return _FakeResp({"translations": [{"text": "Cześć"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    p = DeepLProvider(auth_key="key:fx", use_free=True)
    out = p.complete(CompletionRequest(
        prompt="String to translate:\nHello",
        model="unused",
        options={"target_lang": "pl"},
    ))
    assert out == "Cześć"
    assert "api-free.deepl.com" in seen["url"]
    assert "target_lang=PL" in seen["body"]


def test_deepl_uses_structured_request_metadata(monkeypatch) -> None:
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["body"] = req.data.decode("utf-8")
        return _FakeResp({"translations": [{"text": "Cześć"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    p = DeepLProvider(auth_key="key:fx", use_free=True)
    out = p.complete(CompletionRequest(
        prompt="this prompt is deliberately not parseable",
        model="unused",
        source_texts=["Hello"],
        target_locale="pl",
    ))
    assert out == "Cześć"
    assert "text=Hello" in seen["body"]
    assert "target_lang=PL" in seen["body"]


def test_failed_call_still_meters_reported_usage(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from llm_localizator.catalog.budget import BudgetStore
    from llm_localizator.providers import metered_complete

    monkeypatch.setattr(
        "llm_localizator.providers.anthropic.urlopen_json",
        lambda req, timeout, kind: {
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": "cut"}],
            "usage": {"input_tokens": 1000, "output_tokens": 1000},
        },
    )
    project = SimpleNamespace(
        budget_monthly_usd=10, allow_cloud=True, budget_rates=None,
        budget_root=lambda: tmp_path,
    )
    p = AnthropicProvider(api_key="k")
    with pytest.raises(ProviderError):
        metered_complete(project, p, "pl", CompletionRequest(prompt="x", model="claude-haiku-4-5"))
    assert BudgetStore(tmp_path).month_total() > 0


def test_urlopen_json_retries_transient_network_error() -> None:
    import urllib.error

    from llm_localizator.providers.http_retry import urlopen_json

    calls = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def opener(req, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError("reset")
        return Resp()

    out = urlopen_json(object(), 5, "x", urlopen=opener, sleep=lambda s: None)
    assert out == {"ok": True} and len(calls) == 3


def test_deepl_source_lang_has_no_region_and_formality_fallback_bills_all(monkeypatch) -> None:
    from urllib.error import HTTPError  # noqa: F401  (documented intent)

    from llm_localizator.providers.base import ProviderError

    bodies: list[str] = []

    def fake_post(self, pairs, timeout):
        bodies.append(dict(pairs).get("source_lang", "") + "|" + str("formality" in dict(pairs)))
        if "formality" in dict(pairs):
            err = ProviderError("formality unsupported")
            err.http_code = 400
            err.http_detail = "formality is not supported"
            raise err
        return [{"text": "a", "billed_characters": 3}, {"text": "b", "billed_characters": 4}]

    monkeypatch.setattr(DeepLProvider, "_post", fake_post)
    p = DeepLProvider(auth_key="k", source_locale="en-GB")
    p.complete(CompletionRequest(
        prompt="x", model="m", source_texts=["one", "two"], target_locale="pl",
        schema={"type": "array"},
    ))
    assert bodies[0] == "EN|True" and bodies[1] == "EN|False"
    assert p.last_usage == {"billed_characters": 7}


def test_thinking_model_gets_room_for_thinking_in_max_tokens() -> None:
    from llm_localizator.providers.anthropic import THINKING_MIN_MAX_TOKENS, AnthropicProvider
    from llm_localizator.providers.base import CompletionRequest

    payload = AnthropicProvider(api_key="x")._message_payload(
        CompletionRequest(prompt="Save", model="claude-haiku-5-5", options={"max_tokens": 256, "temperature": 0.1}),
        cache_ttl="5m",
    )
    assert payload["max_tokens"] == THINKING_MIN_MAX_TOKENS
    assert "temperature" not in payload and payload["output_config"] == {"effort": "low"}
