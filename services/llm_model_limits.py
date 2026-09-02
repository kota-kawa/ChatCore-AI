"""Provider model limits shared by request construction and context accounting."""

from __future__ import annotations

QWEN_3_6_27B_MODEL = "qwen/qwen3.6-27b"
QWEN_3_6_27B_MAX_OUTPUT_TOKENS = 16_384

MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    QWEN_3_6_27B_MODEL: QWEN_3_6_27B_MAX_OUTPUT_TOKENS,
}


def get_model_max_output_tokens(model_name: str | None) -> int | None:
    """Return the provider's hard output cap for a known model, if one exists."""

    normalized_name = str(model_name or "").strip()
    return MODEL_MAX_OUTPUT_TOKENS.get(normalized_name)


__all__ = [
    "MODEL_MAX_OUTPUT_TOKENS",
    "QWEN_3_6_27B_MAX_OUTPUT_TOKENS",
    "QWEN_3_6_27B_MODEL",
    "get_model_max_output_tokens",
]
