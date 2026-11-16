"""Cloud price table. No network."""

from __future__ import annotations

import pytest

from llm_localizator.catalog.budget import estimate_anthropic_usd
from llm_localizator.catalog.pricing import (
    LONG_AFTER_TOKENS,
    PricingError,
    deepl_usd,
    price_sources,
    token_usd,
)


def test_haiku_matches_published_rate() -> None:
    assert estimate_anthropic_usd("claude-haiku-4-5", 1_000_000, 0) == pytest.approx(1.0)
    assert estimate_anthropic_usd("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(0.10)
    assert estimate_anthropic_usd("claude-sonnet-4-5", 0, 1_000_000) == pytest.approx(15.0)


def test_actual_usd_meters_cache_hits() -> None:
    from llm_localizator.catalog.pricing import actual_usd, model_thinks

    assert model_thinks("claude-haiku-5-5") is True
    # Anthropic: uncached input + cache read at ~0.1×
    bill = actual_usd(
        "anthropic",
        "claude-haiku-5-5",
        {
            "input_tokens": 100_000,
            "output_tokens": 0,
            "cache_read_input_tokens": 900_000,
        },
    )
    assert bill == pytest.approx(
        (100_000 * 0.10 + 900_000 * 0.01) / 1_000_000
    )
    # DeepSeek: hit vs miss
    ds = actual_usd(
        "deepseek",
        "deepseek-flash",
        {
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "prompt_cache_hit_tokens": 800_000,
            "prompt_cache_miss_tokens": 200_000,
        },
    )
    assert ds == pytest.approx(
        (800_000 * 0.006 + 200_000 * 0.30) / 1_000_000
    )


def test_unknown_model_is_not_priced_as_haiku() -> None:
    with pytest.raises(PricingError):
        token_usd("not-a-model", 1000, 500)


def test_openai_long_context_starts_above_cutoff() -> None:
    short = token_usd("gpt-5.6-luna", LONG_AFTER_TOKENS, 0)
    long = token_usd("gpt-5.6-luna", LONG_AFTER_TOKENS + 1, 0)
    assert short == pytest.approx(LONG_AFTER_TOKENS * 0.20 / 1_000_000)
    assert long == pytest.approx((LONG_AFTER_TOKENS + 1) * 0.40 / 1_000_000)


def test_deepseek_ceiling_uses_peak_rate() -> None:
    assert token_usd("deepseek-v4-pro", 1_000_000, 0) == pytest.approx(1.32)
    assert token_usd("deepseek-flash", 0, 1_000_000) == pytest.approx(1.20)


def test_deepl_is_characters_not_tokens() -> None:
    assert deepl_usd(1_000_000) == pytest.approx(27.50)
    figures = price_sources(
        ["hello", "world"],
        kind="deepl",
        model="deepl",
        batch_size=10,
        preamble_chars=5000,
        output_expansion=2.0,
        thinking_tokens=1024,
    )
    assert figures.characters == 10
    assert figures.max_usd == figures.batch_usd
    assert figures.max_usd == pytest.approx(10 * 27.50 / 1_000_000)


def test_single_key_ceiling_exceeds_batched_figure() -> None:
    figures = price_sources(
        ["alpha", "beta"],
        kind="anthropic",
        model="claude-haiku-4-5",
        batch_size=10,
        preamble_chars=4000,
        output_expansion=2.0,
        thinking_tokens=0,
    )
    assert figures.max_usd > figures.batch_usd


def test_rate_override_prices_an_unlisted_model() -> None:
    amount = token_usd(
        "custom-model", 1_000_000, 0,
        overrides={"custom-model": {"input": 9, "output": 1}},
    )
    assert amount == pytest.approx(9.0)

# Measured tokens per char (tiktoken cl100k_base, ~100 char UI sentences).
_MEASURED_CHARS_PER_TOKEN = {
    "zh": 1.03, "th": 1.09, "hi": 1.02, "ar": 1.46, "ru": 2.47,
    "he": 1.06, "el": 1.09, "bn": 0.81, "ka": 0.53,
}


@pytest.mark.parametrize("locale,measured", sorted(_MEASURED_CHARS_PER_TOKEN.items()))
def test_estimate_tokens_never_undercounts_measured_scripts(locale, measured) -> None:
    from llm_localizator.catalog.pricing import estimate_tokens

    chars = 1000
    assert estimate_tokens(chars, locale) >= chars / measured


def test_estimate_tokens_regional_tag_and_latin_default() -> None:
    from llm_localizator.catalog.pricing import estimate_tokens

    assert estimate_tokens(1000, "th-TH") == estimate_tokens(1000, "th")
    assert estimate_tokens(1000, "pl") == 313  # Latin: 1000 / 4 * 1.25
