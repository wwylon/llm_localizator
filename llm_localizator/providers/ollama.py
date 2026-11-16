"""Ollama backend.

Uses stdlib ``urllib`` -- no SDK, no extra dependency. Every knob (URL, options,
keep-alive, timeouts) comes from the project config; there are no module
constants, which is what lets two projects target different servers or models in
the same session.

Completions are streamed as NDJSON. A client timeout closes the socket, which is
what tells Ollama to abort generation -- non-streaming requests keep the GPU
busy until the full reply is ready even after the client has given up.

``/api/tags`` alone is not enough after teardown ``ollama stop``: the daemon
answers while weights are still unloading or cold-loading. ``ensure_ready``
runs a tiny generate with retries so the first real batch does not time out on
that window.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

from .base import CompletionRequest, Provider, ProviderError

__all__ = ["OllamaProvider", "model_installed", "missing_model_message"]

_TAGS_TTL_S = 30
_tags_cache: dict[str, tuple[float, list[str]]] = {}
_WARMUP_PROMPT = "Reply with exactly: OK"
#: Per-attempt budget; cold load of an 8B on a small card often exceeds 30s.
_WARMUP_TIMEOUT_S = 120
#: Tags-ok / generate-fail flaps after unload typically clear within a few tries.
_WARMUP_ATTEMPTS = 5


class OllamaProvider(Provider):
    def __init__(
        self,
        url: str = "http://localhost:11434",
        options: dict | None = None,
        keep_alive: str = "30m",
    ) -> None:
        self.base_url = url.rstrip("/")
        # Low temperature: translation wants deterministic literal output.
        # Ollama's default (0.8) is why models invent placeholders absent from
        # the source. num_gpu=99 forces full GPU offload.
        self.options = options or {"temperature": 0.1, "top_p": 0.9, "num_gpu": 99}
        self.keep_alive = keep_alive

    @property
    def generate_url(self) -> str:
        return f"{self.base_url}/api/generate"

    @property
    def tags_url(self) -> str:
        return f"{self.base_url}/api/tags"

    def complete(self, request: CompletionRequest) -> str:
        # /api/generate has no separate system field. Translate/improve pass
        # rules in CompletionRequest.system (ADR-111 cloud cache split); dropping
        # them makes local models explain instead of translating and trips the
        # consecutive-reject breaker. Match build_single_prompt's old monolith.
        prompt = request.prompt
        system = (request.system or "").strip()
        if system:
            prompt = f"{system}\n{prompt}"
        payload: dict = {
            "model": request.model,
            "prompt": prompt,
            # Stream so a timeout can abort the runner (close → cancel). With
            # stream=false Ollama finishes the whole generation even after the
            # client hangs up, which cascades into back-to-back timeouts.
            "stream": True,
            "options": {**self.options, **request.options},
            "keep_alive": self.keep_alive,
        }
        if request.schema is not None:
            payload["format"] = request.schema
        if request.images:
            payload["images"] = request.images

        req = urllib.request.Request(
            self.generate_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        deadline = time.monotonic() + max(1, int(request.timeout_s))
        parts: list[str] = []
        try:
            # Initial connect / first-byte budget; per-read deadlines tighten below.
            with urllib.request.urlopen(req, timeout=request.timeout_s) as response:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("timed out")
                    _set_socket_timeout(response, max(1.0, remaining))
                    line = response.readline()
                    if not line:
                        break
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(
                            f"Ollama returned invalid JSON: {exc}"
                        ) from exc
                    piece = chunk.get("response")
                    if chunk.get("error"):
                        raise ProviderError(f"Ollama error: {chunk['error']}")
                    if piece:
                        parts.append(str(piece))
                    if chunk.get("done"):
                        break
        except urllib.error.HTTPError as exc:
            # HTTPError is a URLError subclass; handle it first so a missing
            # model (404) is not misreported as "daemon unreachable".
            if exc.code == 404:
                raise ProviderError(
                    f"Ollama model {request.model!r} not found at "
                    f"{self.base_url} (HTTP 404). "
                    f"Run `ollama pull {request.model}` or override --model."
                ) from exc
            raise ProviderError(
                f"Ollama HTTP {exc.code} at {self.base_url}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"{ollama_unreachable_message(self.base_url)} ({exc})"
            ) from exc
        except (TimeoutError, socket.timeout, OSError) as exc:
            # Closing the response (exiting ``with``) signals Ollama to abort.
            raise ProviderError(
                f"{ollama_unreachable_message(self.base_url)} ({exc})"
            ) from exc

        text = _strip_leading_think("".join(parts).strip())
        if not text:
            raise ProviderError("Ollama returned an empty response")
        return text

    def stop(self, model: str) -> None:
        """Best-effort unload so a timed-out runner does not keep VRAM pinned."""
        payload = {"model": model, "keep_alive": 0}
        req = urllib.request.Request(
            self.generate_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                response.read()
        except Exception:
            return

    def health_check(self) -> bool:
        try:
            with urllib.request.urlopen(self.tags_url, timeout=3) as response:
                return response.status == 200
        except Exception:
            return False

    def ensure_ready(self, model: str, *, report=None) -> None:
        """Reachability plus a short generate so cold-load finishes before work."""
        installed = self._load_tags()
        if installed and not model_installed(model, installed):
            raise ProviderError(missing_model_message(model, installed))
        if report:
            report(f"warming up {model}…")
        last_exc: Exception | None = None
        for attempt in range(1, _WARMUP_ATTEMPTS + 1):
            try:
                self.complete(CompletionRequest(
                    prompt=_WARMUP_PROMPT,
                    model=model,
                    timeout_s=_WARMUP_TIMEOUT_S,
                    # Cap generation — we only need proof the runner is live.
                    options={"num_predict": 8, "temperature": 0},
                ))
                if report and attempt > 1:
                    report(f"  warmup ok on attempt {attempt}/{_WARMUP_ATTEMPTS}")
                return
            except ProviderError as exc:
                last_exc = exc
                msg = str(exc)
                # Non-retriable: model absent or bad request (400).
                if (
                    "not found" in msg
                    or "not installed" in msg
                    or "400" in msg
                    or "bad request" in msg.lower()
                ):
                    raise
                if report:
                    report(
                        f"  warmup attempt {attempt}/{_WARMUP_ATTEMPTS} "
                        f"failed: {exc}"
                    )
                if attempt < _WARMUP_ATTEMPTS:
                    delay = min(2 ** (attempt - 1), 15)
                    if report:
                        report(
                            f"  waiting {delay}s before warmup attempt "
                            f"{attempt + 1}/{_WARMUP_ATTEMPTS}"
                        )
                    time.sleep(delay)
        raise ProviderError(
            f"Ollama model {model!r} not ready after {_WARMUP_ATTEMPTS} "
            f"warmup attempts: {last_exc}"
        )

    def available_models(self) -> list[str]:
        try:
            return self._load_tags()
        except ProviderError:
            return []

    def _load_tags(self) -> list[str]:
        """Model names from ``/api/tags``. Shared across provider instances."""
        now = time.monotonic()
        cached = _tags_cache.get(self.tags_url)
        if cached is not None and now - cached[0] < _TAGS_TTL_S:
            return list(cached[1])
        try:
            with urllib.request.urlopen(self.tags_url, timeout=5) as response:
                data = json.loads(response.read())
        except Exception as exc:
            raise ProviderError(
                f"{ollama_unreachable_message(self.base_url)} ({exc})"
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                f"Ollama /api/tags at {self.base_url} returned a non-object payload."
            )
        models = data.get("models", [])
        if not isinstance(models, list):
            raise ProviderError(
                f"Ollama /api/tags at {self.base_url} returned an invalid models list."
            )
        names: list[str] = []
        for row in models:
            if not isinstance(row, dict):
                continue
            name = row.get("name", "")
            if isinstance(name, str) and name:
                names.append(name)
        names = sorted(names)
        _tags_cache[self.tags_url] = (now, names)
        return list(names)


def _strip_leading_think(text: str) -> str:
    """Drop a leading ``<think>…</think>`` block or a stray ``</think>``.

    Some reasoning-tuned GGUFs (Qwen-based) emit the closing tag, or a whole
    reasoning block, before the answer even with thinking disabled. Only the
    start of the reply is touched; a tag later in the text is real content.
    """
    if text.startswith("<think>"):
        end = text.find("</think>")
        if end == -1:
            return text
        return text[end + len("</think>"):].strip()
    if text.startswith("</think>"):
        return text[len("</think>"):].strip()
    return text


def model_installed(model: str, installed: list[str]) -> bool:
    """Match config pins against ``/api/tags`` names (often ``name:latest``).

    A tagless pin matches the exact name, ``name:latest``, or exactly one
    ``name:*`` tag. Several size tags are ambiguous and do not match.
    """
    names = set(installed)
    if model in names:
        return True
    if ":" in model:
        return False
    # Tagless pin: one size tag (including :latest) is unambiguous. Two or
    # more are not — latest plus llama3.2:8b must not silently pick one.
    matches = [name for name in names if name.startswith(f"{model}:")]
    return len(matches) == 1


OLLAMA_INSTALL_URL = "https://ollama.com"


def ollama_unreachable_message(base_url: str) -> str:
    """User-facing text when the local Ollama daemon does not answer."""
    return (
        f"Ollama is not reachable at {base_url}. "
        f"Install it from {OLLAMA_INSTALL_URL}, start it with `ollama serve`, "
        "then retry (pull your project model with `ollama pull <tag>` if needed)."
    )


def missing_model_message(model: str, installed: list[str]) -> str:
    return (
        f"Ollama model {model!r} is not installed. "
        f"Installed: {', '.join(installed) if installed else '(none)'}. "
        f"Run `ollama pull {model}` or override --model. "
        f"If Ollama itself is missing, install it from {OLLAMA_INSTALL_URL}."
    )


def _set_socket_timeout(response: object, timeout_s: float) -> None:
    """Tighten the recv deadline on an open urllib response, if possible."""
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None) if fp is not None else None
    sock = getattr(raw, "_sock", None) if raw is not None else None
    if sock is not None and hasattr(sock, "settimeout"):
        try:
            sock.settimeout(timeout_s)
        except OSError:
            return
