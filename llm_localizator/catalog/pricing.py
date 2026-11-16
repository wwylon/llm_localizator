"""Published cloud prices and a pre-flight maximum.

Snapshot date is ``PRICE_AS_OF``. Operators override a row under
``[budget.rates]`` without a model bakeoff. Unknown models are an error:
guessing a cheap rate would under-quote.

The ceiling prices the expensive path (one request per string, preamble
repeated). ``batch_usd`` prices the happy path (one preamble per batch) so
the ceiling is not mistaken for the likely bill. Neither number is the bill.
The bill is :func:`actual_usd` from provider usage after the call.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "PRICE_AS_OF",
    "LONG_AFTER_TOKENS",
    "PricingError",
    "TokenPrice",
    "CostFigures",
    "CLOUD_DEFAULT_MODEL",
    "estimate_tokens",
    "token_usd",
    "deepl_usd",
    "actual_usd",
    "fallback_usd",
    "price_sources",
    "model_thinks",
]

PRICE_AS_OF = "2026-11-01"
#: OpenAI bills the whole request at long-context rates above this input size.
LONG_AFTER_TOKENS = 272_000
#: DeepL API Growth pay-as-you-go, USD per million source characters.
DEEPL_USD_PER_MILLION_CHARS = 27.50

CLOUD_DEFAULT_MODEL = {
    "openai": "gpt-5.6-luna",
    "anthropic": "claude-haiku-5-5",
    "deepseek": "deepseek-flash",
    "deepl": "deepl",
}


class PricingError(ValueError):
    """No published or configured price for this model."""


@dataclass(frozen=True)
class TokenPrice:
    input_per_million: float
    output_per_million: float
    long_input_per_million: float | None = None
    long_output_per_million: float | None = None
    long_after_tokens: int | None = None
    thinking: bool = False
    # Prompt-cache rates (USD / 1M tokens). None → derive from input
    # (read ≈ 0.1×, write ≈ 1.25×) except when a vendor publishes fixed hits.
    cache_read_per_million: float | None = None
    cache_write_per_million: float | None = None


@dataclass(frozen=True)
class CostFigures:
    """``max_usd`` is the ceiling. ``batch_usd`` is the batched estimate."""

    max_usd: float
    batch_usd: float
    input_tokens: int
    output_tokens: int
    characters: int
    requests: int


# USD per 1M tokens. OpenAI long-context columns apply only past LONG_AFTER_TOKENS.
# DeepSeek rows are weekday peak (the job may run later). Anthropic is list price.
_TOKEN_PRICES: dict[str, TokenPrice] = {
    "gpt-6-astra": TokenPrice(10.0, 50.0, 20.0, 75.0, LONG_AFTER_TOKENS),
    "gpt-5.6-sol": TokenPrice(4.0, 20.0, 8.0, 30.0, LONG_AFTER_TOKENS),
    "gpt-5.6-terra": TokenPrice(2.0, 12.0, 4.0, 18.0, LONG_AFTER_TOKENS),
    "gpt-5.6-luna": TokenPrice(
        0.20, 1.20, 0.40, 1.80, LONG_AFTER_TOKENS,
        cache_read_per_million=0.02, cache_write_per_million=0.25,
    ),
    "claude-fable-5-1": TokenPrice(10.0, 50.0, thinking=True),
    "claude-opus-5": TokenPrice(5.0, 25.0, thinking=True),
    "claude-sonnet-5": TokenPrice(2.0, 10.0, thinking=True),
    # Haiku 5.5 short-prompt list (≤100k). Adaptive thinking.
    "claude-haiku-5-5": TokenPrice(
        0.10, 0.50, thinking=True,
        cache_read_per_million=0.01, cache_write_per_million=0.125,
    ),
    "claude-haiku-4-5": TokenPrice(1.0, 5.0),
    "claude-haiku-4-5-20251001": TokenPrice(1.0, 5.0),
    "claude-sonnet-4-5": TokenPrice(3.0, 15.0),
    "deepseek-v4-pro": TokenPrice(
        1.32, 3.96, cache_read_per_million=0.044, cache_write_per_million=None,
    ),
    # Peak cache-miss ceiling; actual_usd uses cache_read when the API reports hits.
    "deepseek-flash": TokenPrice(
        0.30, 1.20, cache_read_per_million=0.006, cache_write_per_million=None,
    ),
}


def model_thinks(model: str, overrides: dict | None = None) -> bool:
    price = _lookup(model, overrides, required=False)
    return bool(price and price.thinking)


# Chars per token by language, all upper-bound (low) values. Latin defaults to
# 4.0. Measured with tiktoken cl100k_base on a ~100 char UI sentence (the
# denser tokenizer of the two OpenAI families; Anthropic and DeepSeek vocabularies
# are not public, so the lower of the measurements is used and rounded down):
#   zh 1.03  th 1.09  hi 1.02  ar 1.46  ru 2.47  he 1.06  el 1.09  bn 0.81
#   ka 0.53  (o200k_base is 1.5 to 4.1 for the same strings.)
# Underestimating breaks the max_usd ceiling, so never raise one of these
# without a fresh measurement. Scripts with no measurement use their nearest
# measured relative.
_CHARS_PER_TOKEN: dict[str, float] = {
    "zh": 1.0, "ja": 1.0, "ko": 1.2,
    "th": 1.0, "lo": 1.0, "km": 0.8, "my": 0.8,
    "hi": 1.0, "mr": 1.0, "ne": 1.0, "sa": 1.0,
    "bn": 0.8, "as": 0.8, "ta": 0.8, "te": 0.8, "ml": 0.8, "kn": 0.8,
    "gu": 0.8, "pa": 0.8, "si": 0.8,
    "ka": 0.5, "hy": 0.6,
    "ar": 1.4, "fa": 1.4, "ur": 1.4, "ps": 1.4,
    "he": 1.0, "yi": 1.0,
    "el": 1.0,
    "ru": 2.4, "uk": 2.4, "bg": 2.4, "sr": 2.4, "be": 2.4, "mk": 2.4, "kk": 2.4,
}
# Kept for callers that imported the old CJK-only name.
_CJK_CHARS_PER_TOKEN = _CHARS_PER_TOKEN


def estimate_tokens(chars: int, locale: str = "") -> int:
    """Upper bound: ``chars / cpt`` times a 1.25 safety factor.

    ``cpt`` (chars per token) defaults to 4.0 for Latin scripts but is
    reduced for CJK and other non-Latin scripts (see ``_CHARS_PER_TOKEN``).
    """
    if chars <= 0:
        return 0
    root = locale.replace("_", "-").split("-")[0].lower()
    cpt = _CHARS_PER_TOKEN.get(root, 4.0)
    return math.ceil(chars / cpt * 1.25)


def token_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    overrides: dict | None = None,
) -> float:
    price = _lookup(model, overrides, required=True)
    assert price is not None
    in_rate = price.input_per_million
    out_rate = price.output_per_million
    cutoff = price.long_after_tokens
    if (
        cutoff is not None
        and input_tokens > cutoff
        and price.long_input_per_million is not None
        and price.long_output_per_million is not None
    ):
        in_rate = price.long_input_per_million
        out_rate = price.long_output_per_million
    return (int(input_tokens) * in_rate + int(output_tokens) * out_rate) / 1_000_000


def deepl_usd(characters: int, *, overrides: dict | None = None) -> float:
    rate = DEEPL_USD_PER_MILLION_CHARS
    row = _rate_row(overrides, "deepl")
    if row and "usd_per_million_chars" in row:
        rate = float(row["usd_per_million_chars"])
    return max(0, int(characters)) * rate / 1_000_000


def actual_usd(
    kind: str,
    model: str,
    usage: dict | None,
    *,
    overrides: dict | None = None,
) -> float:
    """Bill from provider usage. Zero when the provider reported nothing.

    Prefer explicit cache hit/miss fields when present so ledger ``actual_usd``
    reflects Anthropic/OpenAI/DeepSeek prompt-cache discounts (ADR cloud cost).
    """
    usage = usage or {}
    if kind == "deepl":
        chars = int(usage.get("billed_characters") or 0)
        if chars <= 0:
            return 0.0
        return deepl_usd(chars, overrides=overrides)
    incoming = int(usage.get("input_tokens") or 0)
    outgoing = int(usage.get("output_tokens") or 0)
    if incoming <= 0 and outgoing <= 0:
        return 0.0
    cache_read = int(
        usage.get("cache_read_input_tokens")
        or usage.get("prompt_cache_hit_tokens")
        or usage.get("cached_tokens")
        or 0
    )
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    # OpenAI reports cached_tokens inside the prompt total; treat as read-only.
    if cache_read > 0 or cache_write > 0:
        price = _lookup(model, overrides, required=True)
        assert price is not None
        read_rate = (
            price.cache_read_per_million
            if price.cache_read_per_million is not None
            else price.input_per_million * 0.1
        )
        write_rate = (
            price.cache_write_per_million
            if price.cache_write_per_million is not None
            else price.input_per_million * 1.25
        )
        # DeepSeek: miss tokens are already full-price input; hit is separate.
        # Anthropic: input_tokens is uncached; cache_* are additive.
        # OpenAI: input includes cached; subtract cached from full-rate input.
        if kind == "deepseek":
            miss = int(usage.get("prompt_cache_miss_tokens") or max(0, incoming - cache_read))
            hit = cache_read
            return (
                hit * read_rate
                + miss * price.input_per_million
                + outgoing * price.output_per_million
            ) / 1_000_000
        if kind == "openai" or usage.get("cached_tokens"):
            uncached = max(0, incoming - cache_read)
            return (
                cache_read * read_rate
                + uncached * price.input_per_million
                + outgoing * price.output_per_million
            ) / 1_000_000
        # Anthropic-style: input_tokens + cache_read + cache_creation
        return (
            incoming * price.input_per_million
            + cache_read * read_rate
            + cache_write * write_rate
            + outgoing * price.output_per_million
        ) / 1_000_000
    return token_usd(model, incoming, outgoing, overrides=overrides)


def fallback_usd(kind: str, usage: dict | None) -> float:
    """Bill for a call whose model has no known price.

    Counts at the highest published rate (long-context columns included) so
    an unpriced model can only over-count against the cap, never hide spend.
    """
    usage = usage or {}
    if kind == "deepl":
        return deepl_usd(int(usage.get("billed_characters") or 0))
    incoming = max(0, int(usage.get("input_tokens") or 0))
    outgoing = max(0, int(usage.get("output_tokens") or 0))
    in_rate = max(
        max(p.input_per_million, p.long_input_per_million or 0.0)
        for p in _TOKEN_PRICES.values()
    )
    out_rate = max(
        max(p.output_per_million, p.long_output_per_million or 0.0)
        for p in _TOKEN_PRICES.values()
    )
    return (incoming * in_rate + outgoing * out_rate) / 1_000_000


def price_sources(
    sources: list[str],
    *,
    kind: str,
    model: str,
    batch_size: int,
    preamble_chars: int,
    output_expansion: float,
    thinking_tokens: int,
    overrides: dict | None = None,
    locale: str = "",
) -> CostFigures:
    """Price ``sources``. DeepL uses source characters, not the chat prompt."""
    texts = [s for s in sources if isinstance(s, str)]
    characters = sum(len(s) for s in texts)
    if kind == "deepl":
        amount = deepl_usd(characters, overrides=overrides)
        return CostFigures(
            max_usd=amount,
            batch_usd=amount,
            input_tokens=0,
            output_tokens=0,
            characters=characters,
            requests=len(texts),
        )
    if not texts:
        return CostFigures(0.0, 0.0, 0, 0, 0, 0)

    expansion = float(output_expansion) if output_expansion > 0 else 2.0
    think = int(thinking_tokens) if model_thinks(model, overrides) else 0
    think = max(0, think)
    preamble = max(0, int(preamble_chars))

    max_in = 0
    max_out = 0
    max_usd = 0.0
    for source in texts:
        in_tok, out_tok = _one_request(preamble, [source], expansion, think, locale)
        max_in += in_tok
        max_out += out_tok
        max_usd += token_usd(model, in_tok, out_tok, overrides=overrides)

    size = max(1, int(batch_size))
    batch_usd = 0.0
    requests = 0
    for start in range(0, len(texts), size):
        chunk = texts[start:start + size]
        in_tok, out_tok = _one_request(preamble, chunk, expansion, think, locale)
        batch_usd += token_usd(model, in_tok, out_tok, overrides=overrides)
        requests += 1
    return CostFigures(
        max_usd=max_usd,
        batch_usd=batch_usd,
        input_tokens=max_in,
        output_tokens=max_out,
        characters=characters,
        requests=requests,
    )


def _one_request(
    preamble_chars: int,
    sources: list[str],
    expansion: float,
    thinking_tokens: int,
    locale: str = "",
) -> tuple[int, int]:
    body = preamble_chars + sum(len(s) for s in sources)
    incoming = estimate_tokens(body, locale)
    source_tokens = sum(estimate_tokens(len(s), locale) for s in sources)
    outgoing = math.ceil(source_tokens * expansion) + thinking_tokens
    return incoming, outgoing


def _lookup(model: str, overrides: dict | None, *, required: bool) -> TokenPrice | None:
    base = _TOKEN_PRICES.get(model)
    row = _rate_row(overrides, model)
    if row is None:
        if base is None and required:
            raise PricingError(
                f"unknown model {model!r} (price snapshot {PRICE_AS_OF}). "
                "Set [budget.rates.<model>] input and output, or pick a listed model."
            )
        return base
    if base is None and ("input" not in row or "output" not in row):
        raise PricingError(
            f"[budget.rates.{model}] needs input and output (USD per 1M tokens)"
        )
    return TokenPrice(
        input_per_million=float(row.get("input", base.input_per_million if base else 0)),
        output_per_million=float(row.get("output", base.output_per_million if base else 0)),
        long_input_per_million=_optional_float(
            row, "long_input", base.long_input_per_million if base else None,
        ),
        long_output_per_million=_optional_float(
            row, "long_output", base.long_output_per_million if base else None,
        ),
        long_after_tokens=_optional_int(
            row, "long_after_tokens", base.long_after_tokens if base else None,
        ),
        thinking=bool(row.get("thinking", base.thinking if base else False)),
        cache_read_per_million=_optional_float(
            row, "cache_read", base.cache_read_per_million if base else None,
        ),
        cache_write_per_million=_optional_float(
            row, "cache_write", base.cache_write_per_million if base else None,
        ),
    )


def _rate_row(overrides: dict | None, model: str) -> dict | None:
    if not overrides:
        return None
    row = overrides.get(model)
    if row is None:
        return None
    if not isinstance(row, dict):
        raise PricingError(f"[budget.rates.{model}] must be a table")
    return row


def _optional_float(row: dict, key: str, fallback: float | None) -> float | None:
    if key not in row:
        return fallback
    return float(row[key])


def _optional_int(row: dict, key: str, fallback: int | None) -> int | None:
    if key not in row:
        return fallback
    return int(row[key])
