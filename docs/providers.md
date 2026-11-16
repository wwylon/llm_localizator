# LLM providers

Backends sit behind one interface in `llm_localizator/providers/`. A project
picks a default with `[provider]`; optional `[providers.<id>]` names extra
endpoints (ADR-47). Per-locale routing uses `[locales.providers]` (id or
legacy kind string).

One interface, one method.

```python
class Provider(abc.ABC):
    @abc.abstractmethod
    def complete(self, request: CompletionRequest) -> str:
        """Return the model's text response.

        Raises ProviderError on any failure. Never returns None -- an empty
        completion is an error, not a value.
        """

    def health_check(self) -> bool: ...

    def ensure_ready(self, model: str, *, report=None) -> None:
        """Block until ``model`` can serve, or raise ProviderError.

        Default is reachability only. Ollama overrides this with a short
        generate warmup (retries) so cold-load after teardown does not kill
        the first real batch.
        """
```

```python
@dataclass
class CompletionRequest:
    prompt: str
    model: str
    schema: dict | None = None    # JSON Schema for structured output
    timeout_s: int = 300
    options: dict = field(default_factory=dict)
```

## Shipped

### `ollama`

Stdlib `urllib` — no SDK, no dependency. Every knob comes from
`[provider]` in the config; there are no module constants, which is what lets
two projects target different servers or models in the same session.

`schema` maps to Ollama's `format` field, constraining batch responses to a JSON
array of exactly *N* strings.

### `null`

A deterministic in-process double. This is the keystone of the test suite
(ADR-5): the whole default suite runs with no Ollama, no network, and no GPU.

```python
NullProvider()                                  # echoes inputs back
NullProvider(handler=lambda req: "...")         # full control
NullProvider(responses=["first", "second"])     # canned queue
NullProvider(fail_on="POISON")                  # exercise error paths
```

It records every call in `.calls`, so a test can assert on what actually reached
the prompt — that a pivot reference was included, that neighbouring sections
were supplied as context, that a batch was split at the right size.

Exhausting `responses` raises rather than returning a default. That is
deliberate: a test making more calls than it declared has drifted from its
intent, and should say so.

## Why injection rather than patching

The original scripts monkey-patched module functions with positional lambdas:

```python
lm.call_ollama = lambda text, lang, model, ctx, gloss, pivot=None: f"[{lang}] {text}"
```

Two costs. A signature change breaks every fake **silently**, leaving tests that
pass while exercising nothing. And the save/restore boilerplate was duplicated
across four test files, which is how they ended up with four subtly different
versions of the same setup.

Injecting a provider instance makes signature drift an immediate error and
reduces setup to one shared fixture.

## Choosing a model

Do not pick Ollama tags by vibe. Follow
[model-evaluation.md](model-evaluation.md) (dual-track bakeoff, incumbent
always included, ADR-12 Winner note before TOML edits).

## Adding a backend

Implement `complete`, raise `ProviderError` on failure, register it:

```python
# llm_localizator/providers/__init__.py
_PROVIDERS = {"ollama": OllamaProvider, "null": NullProvider, "openai": OpenAIProvider}
```

Two things to get right:

**Structured output.** If the backend supports constrained decoding, map
`request.schema` onto it. If not, ignore it — the batch parser already tolerates
a model that wraps its array in prose, and falls back to per-key calls when the
response cannot be parsed at all.

**Errors are exceptions, not sentinels.** The pipeline catches `ProviderError`
and records a skip, keeping the previous translation. Returning `None` or an
empty string instead would be recorded as a successful empty translation.
