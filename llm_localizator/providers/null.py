"""Deterministic in-process provider for tests.

This is the keystone of the test suite (ADR-5). It replaces the module-function
monkey-patching the original scripts required, so pipeline tests run with no
Ollama, no GPU, no network, and no chance of a stale fake silently passing.

The default behaviour echoes the source string with a locale tag, which is
enough to prove routing, batching, checkpointing, and state updates. Tests that
need specific output pass ``responses`` or ``handler``.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from .base import CompletionRequest, Provider, ProviderError
from ._prompt_utils import numbered_lines as _numbered_lines

__all__ = ["NullProvider"]


class NullProvider(Provider):
    """A provider that fabricates answers without leaving the process.

    Parameters
    ----------
    handler:
        Called with the request; returns the completion string. Overrides
        everything else.
    responses:
        A queue of canned completions, consumed in order. Exhausting it raises,
        which is deliberate -- a test that makes more calls than it declared is
        a test that has drifted from its intent.
    fail_on:
        Substring; any prompt containing it raises :class:`ProviderError`, for
        exercising the batch-failure and skip paths.
    """

    def __init__(
        self,
        handler: Callable[[CompletionRequest], str] | None = None,
        responses: list[str] | None = None,
        fail_on: str | None = None,
    ) -> None:
        self.handler = handler
        self.responses = list(responses) if responses is not None else None
        self.fail_on = fail_on
        self.calls: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> str:
        self.calls.append(request)

        if self.fail_on and self.fail_on in request.prompt:
            raise ProviderError(f"NullProvider configured to fail on {self.fail_on!r}")

        if self.handler is not None:
            return self.handler(request)

        if self.responses is not None:
            if not self.responses:
                raise ProviderError(
                    f"NullProvider ran out of canned responses "
                    f"(call #{len(self.calls)})"
                )
            return self.responses.pop(0)

        return self._echo(request)

    @staticmethod
    def _echo(request: CompletionRequest) -> str:
        """Echo the inputs back, honouring the batch schema when one is set."""
        if request.schema is not None:
            count = request.schema.get("minItems", 0)
            lines = _numbered_lines(request.prompt)
            if not lines and count:
                lines = [f"item {i + 1}" for i in range(count)]
            return json.dumps(lines, ensure_ascii=False)
        return request.prompt.strip().splitlines()[-1] if request.prompt.strip() else ""

    @property
    def call_count(self) -> int:
        return len(self.calls)
