"""Smoke tests against a real Ollama server.

Everything else in the suite injects a ``NullProvider`` and never opens a
socket, which is what keeps it fast and hermetic. That leaves one thing
untested: the actual HTTP path. ``providers/ollama.py`` sat at 31% coverage for
exactly this reason -- every line that builds a request, parses a response, or
handles a timeout was only ever exercised by hand.

These tests fill that gap. They are marked ``ollama`` and excluded from the
default run and from the queue blueprint, because they need a live server and a
pulled model, and because they are slow enough to be irritating in a tight loop.

    pytest -m ollama                    # run them
    pytest -m ollama --model llama3.2   # against a specific model

They assert on *shape*, never on translated content: a model is free to render
"Claim" a dozen defensible ways, and a test that pins one of them is a test that
fails for the wrong reason. What must hold is that placeholders survive, ICU
plurals keep their categories, and the transport behaves.
"""

from __future__ import annotations

import json
import time

import pytest

from llm_localizator.core.icu import extract_placeholders, extract_plural_categories
from llm_localizator.pipeline.prompts import BATCH_SCHEMA, BatchItem, build_batch_prompt, build_single_prompt
from llm_localizator.providers import CompletionRequest, OllamaProvider, ProviderError

pytestmark = pytest.mark.ollama

MODEL = "llama3.2"


@pytest.fixture(scope="module")
def provider() -> OllamaProvider:
    p = OllamaProvider()
    if not p.health_check():
        pytest.skip("no Ollama server on http://localhost:11434")
    if not any(m.startswith(MODEL) for m in p.available_models()):
        pytest.skip(f"model {MODEL} is not pulled")
    return p


# ---- transport -------------------------------------------------------------

def test_health_check_succeeds_against_a_live_server(provider: OllamaProvider) -> None:
    assert provider.health_check() is True


def test_health_check_is_false_for_a_dead_port() -> None:
    """Must return False, not raise -- the pipeline calls this to fail fast."""
    assert OllamaProvider(url="http://localhost:59999").health_check() is False


def test_available_models_lists_something(provider: OllamaProvider) -> None:
    models = provider.available_models()
    assert models and all(isinstance(m, str) for m in models)


def test_unreachable_server_raises_provider_error() -> None:
    dead = OllamaProvider(url="http://localhost:59999")
    with pytest.raises(ProviderError, match="unreachable|failed"):
        dead.complete(CompletionRequest(prompt="hi", model=MODEL, timeout_s=3))


def test_timeout_raises_provider_error_rather_than_hanging(provider: OllamaProvider) -> None:
    started = time.monotonic()
    with pytest.raises(ProviderError):
        provider.complete(CompletionRequest(
            prompt="Write an exhaustive history of contract bridge.",
            model=MODEL, timeout_s=1,
        ))
    assert time.monotonic() - started < 20, "a 1s timeout must not hang"


def test_unknown_model_raises_provider_error(provider: OllamaProvider) -> None:
    with pytest.raises(ProviderError):
        provider.complete(CompletionRequest(
            prompt="hi", model="definitely-not-a-real-model:0b", timeout_s=30,
        ))


# ---- completion ------------------------------------------------------------

def test_single_completion_returns_non_empty_text(provider: OllamaProvider) -> None:
    out = provider.complete(CompletionRequest(
        prompt=build_single_prompt(BatchItem(source="Claim"), "Polish",
                                   "a bridge card-game web application", ""),
        model=MODEL, timeout_s=120,
    ))
    assert out.strip()


def test_structured_output_returns_a_json_array(provider: OllamaProvider) -> None:
    """The `format` schema is what keeps batch responses parseable."""
    items = [BatchItem(source=s) for s in ("Claim", "Concede", "Pass")]
    schema = {**BATCH_SCHEMA, "minItems": 3, "maxItems": 3}
    raw = provider.complete(CompletionRequest(
        prompt=build_batch_prompt(items, "Polish", "pl",
                                  "a bridge card-game web application", ""),
        model=MODEL, schema=schema, timeout_s=300,
    ))
    parsed = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
    assert isinstance(parsed, list)
    assert len(parsed) == 3
    assert all(isinstance(s, str) and s.strip() for s in parsed)


def test_placeholders_survive_a_real_translation(provider: OllamaProvider) -> None:
    """Shape, not content: the model may word it freely, but {name} must survive."""
    source = "Welcome back, {name}"
    out = provider.complete(CompletionRequest(
        prompt=build_single_prompt(BatchItem(source=source), "Polish",
                                   "a bridge card-game web application", ""),
        model=MODEL, timeout_s=120,
    ))
    assert extract_placeholders(source) <= extract_placeholders(out), (
        f"placeholder lost: {out!r}"
    )


def test_options_reach_the_server(provider: OllamaProvider) -> None:
    """A per-request option override must be accepted, not rejected."""
    out = provider.complete(CompletionRequest(
        prompt="Reply with exactly one word.", model=MODEL,
        timeout_s=120, options={"num_predict": 5},
    ))
    assert out.strip()


# ---- end to end ------------------------------------------------------------

def test_full_translate_round_trip(tmp_path, provider) -> None:
    """The whole pipeline against a live model, writing real files."""
    from llm_localizator.catalog import JsonNestedCatalog, StateStore
    from llm_localizator.pipeline.translate import run_translation
    from llm_localizator.projects.config import ProjectConfig, ProviderConfig

    from ..conftest import write_json

    write_json(tmp_path / "messages" / "en" / "app.json",
               {"claim": "Claim", "greet": "Hello {name}"})
    cfg = ProjectConfig(
        root=tmp_path, name="smoke", targets=["pl"],
        catalog_path="messages/{locale}/{namespace}.json",
        models={"default": MODEL},
        provider=ProviderConfig(kind="ollama"),
        domain="a bridge card-game web application",
        state_dir=tmp_path / "messages" / ".state",
        translate_min_keys=0,  # two keys, below the default tiny-job floor of 50
    )
    catalog = JsonNestedCatalog(tmp_path, cfg.catalog_path, "en")

    result = run_translation(cfg, catalog, provider, report=lambda _m: None)

    assert result.written >= 1, f"nothing written; rejected={result.rejected}"
    out = catalog.load("pl", "app")
    assert out["claim"] != "Claim" or "claim" in [r.split(".")[-1] for r in result.rejected]
    if "greet" not in " ".join(result.rejected):
        assert "{name}" in out["greet"]

    entry = StateStore(cfg.state_dir).entry("pl", "app", "claim")
    if entry:
        assert entry["model"] == MODEL
        assert entry["translated_at"].endswith("Z")


@pytest.mark.parametrize("locale,language,required", [
    ("pl", "Polish", {"one", "few", "many", "other"}),
])
def test_plural_categories_in_a_real_translation(
    provider: OllamaProvider, locale: str, language: str, required: set[str]
) -> None:
    """Documents actual model behaviour on multi-category plurals.

    Not a hard assertion: llm_localizator F-020 records that these models produce
    only one/other for some languages, which is precisely why validation rejects
    and the key falls back to source. If this xfail starts passing, that limit
    has moved and F-020 is worth revisiting.
    """
    source = "{n, plural, one {# trick} other {# tricks}}"
    out = provider.complete(CompletionRequest(
        prompt=build_single_prompt(BatchItem(source=source), language,
                                   "a bridge card-game web application", ""),
        model=MODEL, timeout_s=180,
    ))
    got = extract_plural_categories(out)
    if got is None or not required <= got:
        pytest.xfail(f"{locale}: model produced {got}, needs {sorted(required)} (see F-020)")
