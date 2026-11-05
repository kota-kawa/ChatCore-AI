"""リクエスト構築とコンテキスト計算で共有する、プロバイダ側のモデル別出力上限を定義する。

Provider model limits shared by request construction and context accounting.
"""

from __future__ import annotations

QWEN_3_8_27B_MODEL = "qwen/qwen3.8-27b"
QWEN_3_8_27B_MAX_OUTPUT_TOKENS = 16_384

# プロバイダが課す出力トークンの上限。ここに無いモデルは上限なしとして扱う。
# Hard output-token caps imposed by the provider; models absent here have no known cap.
MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    QWEN_3_8_27B_MODEL: QWEN_3_8_27B_MAX_OUTPUT_TOKENS,
    "claude-haiku-5-5": 128_000,
}


def get_model_max_output_tokens(model_name: str | None) -> int | None:
    """既知のモデルについて、プロバイダの出力上限があれば返す。

    Return the provider's hard output cap for a known model, if one exists.
    """

    normalized_name = str(model_name or "").strip()
    return MODEL_MAX_OUTPUT_TOKENS.get(normalized_name)


__all__ = [
    "MODEL_MAX_OUTPUT_TOKENS",
    "QWEN_3_8_27B_MAX_OUTPUT_TOKENS",
    "QWEN_3_8_27B_MODEL",
    "get_model_max_output_tokens",
]
