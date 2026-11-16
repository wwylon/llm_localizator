"""W-12 — cloud retry, translate resume, structured op log; F.6 parked."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

from llm_localizator.catalog.flush_journal import FlushJournal
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers.anthropic import AnthropicProvider
from llm_localizator.providers.base import CompletionRequest, ProviderError
from llm_localizator.providers.http_retry import is_retryable_http, urlopen_json
from llm_localizator.providers.null import NullProvider
from llm_localizator.web.marketing import phase_statuses

from .conftest import setup_project, tagged


class _FakeResp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(code: int, body: bytes = b"err", headers=None):
    return urllib.error.HTTPError(
        "http://example.test/x", code, "error", headers or {}, BytesIO(body),
    )


def test_retryable_codes() -> None:
    assert is_retryable_http(429)
    assert is_retryable_http(503)
    assert not is_retryable_http(400)
    assert not is_retryable_http(401)
    assert not is_retryable_http(404)


def test_urlopen_retries_429_then_succeeds(monkeypatch) -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, b"rate limit")
        return _FakeResp({"ok": True, "content": [{"type": "text", "text": "hi"}]})

    import urllib.request

    req = urllib.request.Request("http://example.test/", data=b"{}", method="POST")
    body = urlopen_json(
        req, 5, "Test",
        sleep=slept.append,
        urlopen=fake_urlopen,
    )
    assert body["ok"] is True
    assert calls["n"] == 2
    assert slept  # backed off once


def test_urlopen_400_fails_once(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        raise _http_error(400, b"bad request")

    import urllib.request

    req = urllib.request.Request("http://example.test/", data=b"{}", method="POST")
    with pytest.raises(ProviderError, match="HTTP 400"):
        urlopen_json(req, 5, "Test", sleep=lambda _d: None, urlopen=fake_urlopen)
    assert calls["n"] == 1


def test_anthropic_429_then_200(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, b"slow down")
        return _FakeResp({"content": [{"type": "text", "text": "Cześć"}]})

    monkeypatch.setattr(
        "llm_localizator.providers.http_retry.urllib.request.urlopen", fake_urlopen,
    )
    monkeypatch.setattr("llm_localizator.providers.http_retry.time.sleep", lambda _d: None)
    p = AnthropicProvider(api_key="test-key")
    assert p.complete(CompletionRequest(prompt="Hello", model="x")) == "Cześć"
    assert calls["n"] == 2


def test_anthropic_400_once(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        raise _http_error(400, b"bad")

    monkeypatch.setattr(
        "llm_localizator.providers.http_retry.urllib.request.urlopen", fake_urlopen,
    )
    monkeypatch.setattr("llm_localizator.providers.http_retry.time.sleep", lambda _d: None)
    p = AnthropicProvider(api_key="test-key")
    with pytest.raises(ProviderError, match="HTTP 400"):
        p.complete(CompletionRequest(prompt="Hello", model="x"))
    assert calls["n"] == 1


def test_resume_does_not_rerequest_finished_keys(
    project_root, make_config, make_catalog, silent,
) -> None:
    setup_project(project_root, {"a": "One", "b": "Two", "c": "Three"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    seen: list[str] = []

    def is_scoring(prompt: str) -> bool:
        # Back-translation and the LQS judge (ADR-20) score a key; they are not a translation request.
        return "back to English" in prompt or "quality judge" in prompt

    def handler(request: CompletionRequest) -> str:
        if is_scoring(request.prompt):
            return tagged(request)
        src = request.prompt.strip().splitlines()[-1]
        if src.startswith("[xx] "):
            src = src[5:]
        seen.append(src)
        if len(seen) > 2:
            raise RuntimeError("crash after key 2")
        return tagged(request)

    provider = NullProvider(handler=handler)
    with pytest.raises(RuntimeError, match="crash after key 2"):
        run_translation(cfg, catalog, provider, batch_size=1, report=silent)

    journal = FlushJournal(cfg.state_root())
    last = journal.last_finished_key()
    assert last is not None
    assert last[0] == "pl"
    assert last[2] in {"a", "b", "c"}
    assert journal.interrupted() is None  # progress is not a flush block
    finished_sources = set(seen[:2])
    assert len(finished_sources) == 2

    calls_before = provider.call_count
    seen.clear()  # count only the resume run
    result = run_translation(cfg, catalog, provider, batch_size=1, report=silent)
    assert result.written >= 1
    new_sources = []
    for call in provider.calls[calls_before:]:
        if is_scoring(call.prompt):
            continue
        line = call.prompt.strip().splitlines()[-1]
        if line.startswith("[xx] "):
            line = line[5:]
        new_sources.append(line)
    for src in finished_sources:
        assert src not in new_sources


def test_dispatch_emits_stderr_json_log(tmp_path, make_config, capsys) -> None:
    setup_project(tmp_path, {"greet": "Hello"}, existing={"greet": "Witaj"})
    cfg = make_config(tmp_path)
    dispatch_op(cfg, "status", {"locales": ["pl"]}, actor_role="Admin")
    assert not capsys.readouterr().err.strip(), "read-only ops do not log"
    result = dispatch_op(cfg, "sync", {"locales": ["pl"], "dry_run": True}, actor_role="Admin")
    assert result.get("ok") is not False
    err = capsys.readouterr().err.strip().splitlines()
    assert err, "expected a stderr JSON line"
    payload = json.loads(err[-1])
    assert payload["command"] == "sync"
    assert "locale" in payload
    assert "keys" in payload
    assert "wall_seconds" in payload
    assert payload["exit"] == 0


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "plan" / "web-platform").is_dir(),
    reason="needs plan/web-platform (private checkout only)",
)
def test_f6_concurrency_stays_parked() -> None:
    """No parallel Ollama without an accepted F.6 ADR."""
    hub = Path(__file__).resolve().parents[1] / "plan" / "web-platform" / "README.md"
    text = hub.read_text(encoding="utf-8")
    assert "F.6" in text
    assert "park" in text.lower() or "Parked" in text
    # Translate path must not open a thread pool for locales.
    src = (
        Path(__file__).resolve().parents[1]
        / "llm_localizator" / "pipeline" / "translate.py"
    ).read_text(encoding="utf-8")
    assert "ThreadPoolExecutor" not in src
    assert "parallel_locales" not in src


def test_phase_statuses_include_w12() -> None:
    rows = {r["id"]: r for r in phase_statuses()}
    assert "W-12" in rows
