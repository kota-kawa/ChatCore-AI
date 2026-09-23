"""Provider price table used to turn API usage into a cost.

料金は各プロバイダの公開価格（2026-09-23 時点）を写したものです。価格改定や
モデル追加のときはこの表を更新してください。
Prices mirror each provider's public price list as of 2026-09-23. Update this table
when a provider changes its prices or a model is added.

金額は整数のナノドル（1e-9 USD）で扱います。「1M トークンあたり $X」は
「1 トークンあたり X*1000 ナノドル」なので、公開価格をそのまま整数で表せ、
浮動小数点の丸め誤差が集計に積もりません。
Costs are integer nano-dollars (1e-9 USD). "$X per 1M tokens" is exactly X*1000
nano-dollars per token, so every published price is an integer and no floating-point
rounding accumulates in the totals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TokenPrice:
    """Per-token prices in nano-dollars."""

    input: int
    output: int
    # キャッシュ割引を公表していないプロバイダは入力と同額として扱う（安全側）。
    # Providers without a published cache discount bill cached input at the input rate.
    cached_input: int | None = None

    def cached_input_or_input(self) -> int:
        return self.input if self.cached_input is None else self.cached_input


# 1M トークンあたりの公開価格 × 1000 = 1 トークンあたりのナノドル。
# Published price per 1M tokens × 1000 = nano-dollars per token.
TOKEN_PRICES: dict[str, TokenPrice] = {
    # OpenAI: https://developers.openai.com/api/docs/models/gpt-6-luna
    "gpt-6-luna": TokenPrice(input=100, cached_input=10, output=500),
    # Groq: https://console.groq.com/docs/model/qwen/qwen3.8-27b
    "qwen/qwen3.8-27b": TokenPrice(input=800, output=4_000),
    "openai/gpt-oss-120b": TokenPrice(input=150, output=600),
    "openai/gpt-oss-20b": TokenPrice(input=75, output=300),
    # Anthropic: $1 / $5 per 1M, cache reads at 0.1x.
    "claude-haiku-4-5-20251001": TokenPrice(input=1_000, cached_input=100, output=5_000),
    # OpenAI embeddings are billed on input only.
    "text-embedding-3-small": TokenPrice(input=20, output=0),
}

# 表に無いモデルは、表で最も高い単価で数える。上限の判定が甘くならないようにするため。
# Unknown models are billed at the most expensive listed rate so a missing entry can never
# make the limits more permissive.
FALLBACK_TOKEN_PRICE = TokenPrice(input=1_000, cached_input=1_000, output=5_000)

# Brave Search API: $5 per 1,000 requests.
BRAVE_WEB_SEARCH_REQUEST_NANO_USD = 5_000_000


def token_price_for_model(model_name: str) -> TokenPrice:
    """Return the price for ``model_name``, falling back to the most expensive rate."""

    price = TOKEN_PRICES.get(model_name)
    if price is not None:
        return price
    logger.warning("No price is registered for model %s; billing at the fallback rate.", model_name)
    return FALLBACK_TOKEN_PRICE


def token_cost_nano_usd(
    model_name: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> int:
    """Return the cost of one request in nano-dollars.

    ``input_tokens`` is the total input, including any cached portion, which matches how
    OpenAI and Groq report usage.
    """

    price = token_price_for_model(model_name)
    cached = min(max(cached_input_tokens, 0), max(input_tokens, 0))
    uncached = max(input_tokens, 0) - cached
    return (
        uncached * price.input
        + cached * price.cached_input_or_input()
        + max(output_tokens, 0) * price.output
    )

