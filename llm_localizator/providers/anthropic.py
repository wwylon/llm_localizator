"""Anthropic Messages API backend (Claude).

Requires ``ANTHROPIC_API_KEY`` in the environment. Never reads secrets from TOML.
Supports prompt caching (``cache_control``) and Message Batches (~50% off).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from .base import CompletionRequest, Provider, ProviderError
from .http_retry import urlopen_json
from .keys import candidate_vars, resolve_api_key

__all__ = ["AnthropicProvider"]

VENDOR_VAR = "ANTHROPIC_API_KEY"
DEFAULT_MODEL = "claude-haiku-5-5"
API_URL = "https://api.anthropic.com/v1/messages"
BATCHES_URL = "https://api.anthropic.com/v1/messages/batches"
API_VERSION = "2023-06-01"
# Prompt-cache + Message Batches beta headers.
CACHE_BETA = "prompt-caching-2024-07-31"
BATCH_BETA = "message-batches-2024-09-24"
#: Room for adaptive thinking plus the answer on thinking models (S1.9 smoke: a one-word key hit max_tokens).
THINKING_MIN_MAX_TOKENS = 4096


def _usage_from_body(usage: dict | None) -> dict | None:
    if not isinstance(usage, dict):
        return None
    out = {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
    }
    # Anthropic reports cache fields alongside uncached input_tokens.
    for src, dst in (
        ("cache_read_input_tokens", "cache_read_input_tokens"),
        ("cache_creation_input_tokens", "cache_creation_input_tokens"),
    ):
        if usage.get(src):
            out[dst] = int(usage[src])
    return out


def _text_from_message(body: dict) -> str:
    parts = body.get("content") or []
    return "".join(
        p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"
    ).strip()


def _batch_note(message: str) -> None:
    """One progress line on stderr (never the key or the text being translated)."""
    try:
        print(message, file=sys.stderr, flush=True)
    except OSError:
        pass


class AnthropicProvider(Provider):
    kind = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        default_model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
        api_key_env: str | None = None,
    ) -> None:
        self.api_key_env = api_key_env
        # None → read env; explicit "" stays empty (do not fall through to env).
        if api_key is None:
            self.api_key = resolve_api_key(VENDOR_VAR, api_key_env).strip()
        else:
            self.api_key = api_key.strip()
        self.default_model = default_model
        self.max_tokens = max_tokens
        self.last_usage: dict | None = None

    def __repr__(self) -> str:
        return f"AnthropicProvider(api_key='***', default_model={self.default_model!r})"

    def _missing_key_message(self) -> str:
        names = " or ".join(candidate_vars(VENDOR_VAR, self.api_key_env))
        return f"Anthropic API key missing — set {names} in the environment"

    def _headers(self, *, batch: bool = False) -> dict[str, str]:
        betas = [CACHE_BETA]
        if batch:
            betas.append(BATCH_BETA)
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "anthropic-beta": ",".join(betas),
        }

    def _message_payload(self, request: CompletionRequest, *, cache_ttl: str) -> dict:
        model = request.model or self.default_model
        payload: dict = {
            "model": model,
            "max_tokens": int(request.options.get("max_tokens", self.max_tokens)),
            "messages": [{"role": "user", "content": request.prompt}],
        }
        system_text = (request.system or "").strip()
        if not system_text and request.schema is not None:
            item = request.schema.get("items", {}) if isinstance(request.schema, dict) else {}
            if isinstance(item, dict) and item.get("properties"):
                shape = "JSON objects matching the requested schema"
            else:
                shape = "a JSON array of strings matching the requested length"
            system_text = f"Respond with ONLY {shape}. No markdown fences."
        if system_text:
            # Opt-in cache breakpoint on the stable system block (ADR cloud cost).
            payload["system"] = [{
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral", "ttl": cache_ttl},
            }]
        temp = request.options.get("temperature")
        if temp is not None:
            payload["temperature"] = float(temp)
        from ..catalog.pricing import model_thinks
        if model_thinks(model):
            payload.pop("temperature", None)
            payload["output_config"] = {"effort": "low"}
            # Thinking (on by default on Haiku 5.5, even at low effort) counts against max_tokens, so a cap sized for
            # the answer alone (len*4+64) truncates short keys. Only used tokens are billed, so a floor costs nothing.
            payload["max_tokens"] = max(payload["max_tokens"], THINKING_MIN_MAX_TOKENS)
        return payload

    def complete(self, request: CompletionRequest) -> str:
        if not self.api_key:
            raise ProviderError(self._missing_key_message())
        self.last_usage = None
        # Sync Messages: 5-minute ephemeral cache. Batch path uses 1h.
        ttl = str(request.options.get("cache_ttl") or "5m")
        payload = self._message_payload(request, cache_ttl=ttl)
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        body = urlopen_json(req, request.timeout_s, "Anthropic")
        text = _text_from_message(body)
        self.last_usage = _usage_from_body(body.get("usage"))
        if body.get("stop_reason") == "max_tokens":
            raise ProviderError("Anthropic hit the token limit (stop_reason=max_tokens)")
        if not text:
            raise ProviderError("Anthropic returned an empty response")
        return text

    def complete_many(self, requests: list[CompletionRequest]) -> list[str]:
        """Submit via Message Batches (~50% off). Falls back to sequential when N<2."""
        if not requests:
            return []
        if len(requests) == 1:
            return [self.complete(requests[0])]
        if not self.api_key:
            raise ProviderError(self._missing_key_message())
        self.last_usage = None
        # Batch cache TTL is 1h so a long poll still reuses the prefix.
        entries = []
        for i, request in enumerate(requests):
            cid = (request.custom_id or f"req-{i}").replace(":", "_")[:64]
            entries.append({
                "custom_id": cid,
                "params": self._message_payload(request, cache_ttl="1h"),
            })
        create_req = urllib.request.Request(
            BATCHES_URL,
            data=json.dumps({"requests": entries}).encode("utf-8"),
            headers=self._headers(batch=True),
            method="POST",
        )
        # Creation timeout: generous; polling uses each request's timeout sum.
        created = urlopen_json(create_req, max(r.timeout_s for r in requests), "Anthropic")
        batch_id = created.get("id")
        if not batch_id:
            raise ProviderError("Anthropic Message Batch create returned no id")
        deadline = time.monotonic() + max(120, sum(max(30, r.timeout_s) for r in requests))
        poll_s = float(requests[0].options.get("batch_poll_s") or 2.0)
        every_s = float(requests[0].options.get("batch_progress_s") or 30.0)
        started = time.monotonic()
        next_note = started
        _batch_note(
            f"Anthropic batch {batch_id}: {len(requests)} request(s) submitted. Batches run "
            "asynchronously at about half price; expect minutes, not seconds."
        )
        while True:
            if time.monotonic() > deadline:
                raise ProviderError(f"Anthropic Message Batch {batch_id} timed out")
            status_req = urllib.request.Request(
                f"{BATCHES_URL}/{batch_id}",
                headers=self._headers(batch=True),
                method="GET",
            )
            status = urlopen_json(status_req, 60, "Anthropic")
            processing = status.get("processing_status") or ""
            if processing != "ended" and time.monotonic() >= next_note:
                next_note = time.monotonic() + every_s
                counts = status.get("request_counts") or {}
                done = sum(int(counts.get(k) or 0) for k in ("succeeded", "errored", "canceled", "expired"))
                _batch_note(
                    f"Anthropic batch {batch_id}: {processing or 'waiting'}, {done}/{len(requests)} done, "
                    f"{int(time.monotonic() - started)}s elapsed"
                )
            if processing == "ended":
                _batch_note(f"Anthropic batch {batch_id}: ended after {int(time.monotonic() - started)}s")
                break
            if processing in {"canceled", "expired"}:
                raise ProviderError(
                    f"Anthropic Message Batch {batch_id} ended as {processing}"
                )
            time.sleep(poll_s)
        results_req = urllib.request.Request(
            f"{BATCHES_URL}/{batch_id}/results",
            headers=self._headers(batch=True),
            method="GET",
        )
        # Results endpoint returns JSONL (one result object per line).
        try:
            with urllib.request.urlopen(results_req, timeout=120) as resp:
                payload_bytes = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise ProviderError(
                f"Anthropic Message Batch results HTTP {exc.code}: {detail}"
            ) from exc
        by_id: dict[str, dict] = {}
        total_in = total_out = total_cache_read = total_cache_write = 0
        for line in payload_bytes.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cid = str(row.get("custom_id") or "")
            by_id[cid] = row
            result = row.get("result") or {}
            msg = result.get("message") if isinstance(result, dict) else None
            if isinstance(msg, dict):
                usage = _usage_from_body(msg.get("usage"))
                if usage:
                    total_in += usage.get("input_tokens", 0)
                    total_out += usage.get("output_tokens", 0)
                    total_cache_read += usage.get("cache_read_input_tokens", 0)
                    total_cache_write += usage.get("cache_creation_input_tokens", 0)
        self.last_usage = {
            "input_tokens": total_in,
            "output_tokens": total_out,
        }
        if total_cache_read:
            self.last_usage["cache_read_input_tokens"] = total_cache_read
        if total_cache_write:
            self.last_usage["cache_creation_input_tokens"] = total_cache_write

        texts: list[str] = []
        for i, request in enumerate(requests):
            cid = (request.custom_id or f"req-{i}").replace(":", "_")[:64]
            row = by_id.get(cid)
            if not row:
                raise ProviderError(f"Anthropic Message Batch missing result for {cid}")
            result = row.get("result") or {}
            rtype = result.get("type") if isinstance(result, dict) else None
            if rtype != "succeeded":
                err = (result.get("error") or {}) if isinstance(result, dict) else {}
                raise ProviderError(
                    f"Anthropic Message Batch item {cid} failed: "
                    f"{err.get('type', rtype)} {err.get('message', '')}".strip()
                )
            msg = result.get("message") or {}
            if msg.get("stop_reason") == "max_tokens":
                raise ProviderError(
                    f"Anthropic Message Batch item {cid} hit token limit"
                )
            text = _text_from_message(msg)
            if not text:
                raise ProviderError(
                    f"Anthropic Message Batch item {cid} returned empty text"
                )
            texts.append(text)
        return texts

    def health_check(self) -> bool:
        return bool(self.api_key)
