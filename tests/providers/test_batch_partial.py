"""Partial cloud-batch failures keep paid-for results (audit B2/B3)."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from llm_localizator.providers import CompletionRequest, ProviderError
from llm_localizator.providers.anthropic import AnthropicProvider
from llm_localizator.providers.batch import PartialBatchError, batch_custom_ids, fetch_jsonl


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _row(cid: str, ok: bool) -> str:
    if ok:
        result = {"type": "succeeded", "message": {
            "content": [{"type": "text", "text": f'["{cid}"]'}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }}
    else:
        result = {"type": "errored", "error": {"type": "overloaded", "message": "x"}}
    return json.dumps({"custom_id": cid, "result": result})


def test_anthropic_partial_failure_keeps_successes_and_usage(monkeypatch) -> None:
    def fake_urlopen_json(req, timeout, kind):
        if req.get_method() == "POST":
            return {"id": "b1"}
        return {"processing_status": "ended"}

    body = ("\n".join([_row("a", True), _row("b", False)]) + "\n").encode()
    monkeypatch.setattr("llm_localizator.providers.anthropic.urlopen_json", fake_urlopen_json)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: _Resp(body))
    p = AnthropicProvider(api_key="k")
    with pytest.raises(PartialBatchError) as info:
        p.complete_many([
            CompletionRequest(prompt="a", system="s", model="m", custom_id="a"),
            CompletionRequest(prompt="b", system="s", model="m", custom_id="b"),
        ])
    assert info.value.results == ['["a"]', None]
    assert set(info.value.errors) == {1}
    # Usage is set so the caller can bill what was spent.
    assert p.last_usage == {"input_tokens": 10, "output_tokens": 5}


def test_batch_custom_ids_unique_after_truncation() -> None:
    long = "x" * 70
    ids = batch_custom_ids([long, long + "y", "a:b", None])
    assert len(set(ids)) == 4
    assert all(len(i) <= 64 and ":" not in i for i in ids)


def test_fetch_jsonl_retries_then_wraps_errors(monkeypatch) -> None:
    calls = {"n": 0}

    def flaky(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("reset")
        if calls["n"] == 2:
            return _Resp(b'{"custom_id": "a"')  # cut-off body
        return _Resp(b'{"custom_id": "a"}\n')

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    rows = fetch_jsonl(object(), "T", sleep=lambda s: None)  # type: ignore[arg-type]
    assert rows == [{"custom_id": "a"}] and calls["n"] == 3

    def always_bad(req, timeout=0):
        raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"nope"))

    monkeypatch.setattr("urllib.request.urlopen", always_bad)
    with pytest.raises(ProviderError):
        fetch_jsonl(object(), "T", sleep=lambda s: None)  # type: ignore[arg-type]
