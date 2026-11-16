"""OpenAI Chat Completions client, also used for DeepSeek.

Keys come from the environment only. Never from TOML or an MCP argument.

OpenAI: automatic prompt caching on a stable system prefix; Batch API (~50%).
DeepSeek: automatic disk KV cache on identical prefixes; no vendor Batch API —
``complete_many`` stays sequential. Translation disables thinking by default.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import CompletionRequest, Provider, ProviderError
from .http_retry import urlopen_json

__all__ = ["OpenAICompatibleProvider"]

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
OPENAI_FILES_URL = "https://api.openai.com/v1/files"
OPENAI_BATCHES_URL = "https://api.openai.com/v1/batches"


def _usage_dict(kind: str, usage: dict | None) -> dict | None:
    if not isinstance(usage, dict):
        return None
    out = {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
    }
    # OpenAI: prompt_tokens_details.cached_tokens
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict) and details.get("cached_tokens"):
        out["cached_tokens"] = int(details["cached_tokens"])
    # DeepSeek: prompt_cache_hit_tokens / prompt_cache_miss_tokens
    if usage.get("prompt_cache_hit_tokens"):
        out["prompt_cache_hit_tokens"] = int(usage["prompt_cache_hit_tokens"])
    if usage.get("prompt_cache_miss_tokens"):
        out["prompt_cache_miss_tokens"] = int(usage["prompt_cache_miss_tokens"])
    return out


def _choice_text(kind: str, body: dict) -> str:
    choices = body.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise ProviderError(f"{kind} returned no choices")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise ProviderError(
            f"{kind} hit the token limit (finish_reason=length)"
        )
    message = choice.get("message") or {}
    text = str(message.get("content") or "").strip()
    if not text:
        raise ProviderError(f"{kind} returned an empty response")
    return text


class OpenAICompatibleProvider(Provider):
    def __init__(
        self,
        *,
        kind: str,
        api_key: str | None = None,
        env_var: str,
        url: str,
        default_model: str,
        reasoning: bool = False,
        disable_thinking: bool = False,
    ) -> None:
        self.kind = kind
        self.api_key = (api_key or os.environ.get(env_var) or "").strip()
        self.env_var = env_var
        self.url = url
        self.default_model = default_model
        self.reasoning = reasoning
        self.disable_thinking = disable_thinking
        self.last_usage: dict | None = None

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleProvider(kind={self.kind!r}, api_key='***', "
            f"default_model={self.default_model!r})"
        )

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _chat_payload(self, request: CompletionRequest) -> dict:
        model = request.model or self.default_model
        messages: list[dict] = []
        system_text = (request.system or "").strip()
        if not system_text and request.schema is not None:
            system_text = "Respond with ONLY the requested JSON. No markdown fences."
        if system_text:
            # Stable system message first → automatic prefix cache (OpenAI / DeepSeek).
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": request.prompt})
        payload: dict = {"model": model, "messages": messages}
        # OpenAI optional cache key keeps routing sticky for long runs.
        cache_key = request.options.get("prompt_cache_key")
        if cache_key and self.kind == "openai":
            payload["prompt_cache_key"] = str(cache_key)
        temp = request.options.get("temperature")
        if temp is not None:
            payload["temperature"] = float(temp)
        if self.reasoning:
            payload["reasoning_effort"] = "low"
        # DeepSeek JSON MT: disable thinking (plan + vendor translation guides).
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        max_tokens = request.options.get("max_tokens")
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        else:
            payload["max_tokens"] = 4096
        return payload

    def complete(self, request: CompletionRequest) -> str:
        if not self.api_key:
            raise ProviderError(
                f"{self.kind} API key missing — set {self.env_var} in the environment"
            )
        self.last_usage = None
        payload = self._chat_payload(request)
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._auth_headers(),
            method="POST",
        )
        body = urlopen_json(req, request.timeout_s, self.kind)
        self.last_usage = _usage_dict(self.kind, body.get("usage"))
        return _choice_text(self.kind, body)

    def complete_many(self, requests: list[CompletionRequest]) -> list[str]:
        """OpenAI Batch API when kind=openai and N≥2; else sequential.

        DeepSeek has no Batch API — lean on prefix cache + off-peak scheduling.
        """
        if not requests:
            return []
        if self.kind != "openai" or len(requests) == 1:
            return [self.complete(r) for r in requests]
        if not self.api_key:
            raise ProviderError(
                f"{self.kind} API key missing — set {self.env_var} in the environment"
            )
        # Build JSONL for /v1/batches (chat.completions endpoint).
        lines: list[str] = []
        id_order: list[str] = []
        for i, request in enumerate(requests):
            cid = (request.custom_id or f"req-{i}").replace(":", "_")[:64]
            id_order.append(cid)
            body = self._chat_payload(request)
            lines.append(json.dumps({
                "custom_id": cid,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }))
        jsonl = ("\n".join(lines) + "\n").encode("utf-8")
        boundary = "----llmLocalizeBatch"
        multipart = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="purpose"\r\n\r\n'
            f"batch\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; '
            f'filename="batch.jsonl"\r\n'
            f"Content-Type: application/jsonl\r\n\r\n"
        ).encode("utf-8") + jsonl + f"\r\n--{boundary}--\r\n".encode("utf-8")
        file_req = urllib.request.Request(
            OPENAI_FILES_URL,
            data=multipart,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        file_body = urlopen_json(file_req, 120, self.kind)
        file_id = file_body.get("id")
        if not file_id:
            raise ProviderError("OpenAI Batch file upload returned no id")
        create_req = urllib.request.Request(
            OPENAI_BATCHES_URL,
            data=json.dumps({
                "input_file_id": file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            }).encode("utf-8"),
            headers=self._auth_headers(),
            method="POST",
        )
        created = urlopen_json(create_req, 60, self.kind)
        batch_id = created.get("id")
        if not batch_id:
            raise ProviderError("OpenAI Batch create returned no id")
        deadline = time.monotonic() + max(120, sum(max(30, r.timeout_s) for r in requests))
        poll_s = float(requests[0].options.get("batch_poll_s") or 2.0)
        output_file_id = None
        while True:
            if time.monotonic() > deadline:
                raise ProviderError(f"OpenAI Batch {batch_id} timed out")
            status_req = urllib.request.Request(
                f"{OPENAI_BATCHES_URL}/{batch_id}",
                headers=self._auth_headers(),
                method="GET",
            )
            status = urlopen_json(status_req, 60, self.kind)
            state = status.get("status") or ""
            if state == "completed":
                output_file_id = status.get("output_file_id")
                break
            if state in {"failed", "expired", "cancelled", "cancelling"}:
                raise ProviderError(f"OpenAI Batch {batch_id} ended as {state}")
            time.sleep(poll_s)
        if not output_file_id:
            raise ProviderError(f"OpenAI Batch {batch_id} completed with no output file")
        content_req = urllib.request.Request(
            f"{OPENAI_FILES_URL}/{output_file_id}/content",
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(content_req, timeout=120) as resp:
                payload_bytes = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise ProviderError(
                f"OpenAI Batch results HTTP {exc.code}: {detail}"
            ) from exc
        by_id: dict[str, dict] = {}
        total_in = total_out = total_cached = 0
        for line in payload_bytes.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cid = str(row.get("custom_id") or "")
            by_id[cid] = row
            resp = (row.get("response") or {}).get("body") or {}
            usage = _usage_dict(self.kind, resp.get("usage") if isinstance(resp, dict) else None)
            if usage:
                total_in += usage.get("input_tokens", 0)
                total_out += usage.get("output_tokens", 0)
                total_cached += usage.get("cached_tokens", 0)
        self.last_usage = {"input_tokens": total_in, "output_tokens": total_out}
        if total_cached:
            self.last_usage["cached_tokens"] = total_cached
        texts: list[str] = []
        for cid in id_order:
            row = by_id.get(cid)
            if not row:
                raise ProviderError(f"OpenAI Batch missing result for {cid}")
            err = row.get("error")
            if err:
                raise ProviderError(f"OpenAI Batch item {cid} failed: {err}")
            resp = (row.get("response") or {})
            body = resp.get("body") or {}
            texts.append(_choice_text(self.kind, body))
        return texts

    def health_check(self) -> bool:
        return bool(self.api_key)
