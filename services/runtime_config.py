import logging
import os

logger = logging.getLogger(__name__)

VALID_SESSION_SAMESITE_VALUES = {"lax", "strict", "none"}


def get_runtime_env() -> str:
    # 新環境変数を優先しつつ、旧変数も後方互換として受け付ける
    # Prefer the new env var while keeping legacy fallback for compatibility.
    runtime_env = os.getenv("FASTAPI_ENV")
    legacy_env = os.getenv("FLASK_ENV")

    if runtime_env:
        if legacy_env and legacy_env != runtime_env:
            logger.warning(
                "Both FASTAPI_ENV and FLASK_ENV are set with different values. "
                "Using FASTAPI_ENV."
            )
        return runtime_env

    if legacy_env:
        logger.warning("FLASK_ENV is deprecated. Use FASTAPI_ENV instead.")
        return legacy_env

    return "development"


def is_production_env() -> bool:
    # 環境文字列比較はここに集約して呼び出し側の分岐を簡潔に保つ
    # Centralize environment check so call sites stay simple.
    return get_runtime_env().lower() == "production"


def get_session_secret_key() -> str | None:
    # セッション署名キーも FASTAPI_* を優先し、FLASK_* はレガシー互換として扱う
    # Resolve session secret with FASTAPI_* priority and FLASK_* legacy fallback.
    fastapi_secret = os.getenv("FASTAPI_SECRET_KEY")
    legacy_secret = os.getenv("FLASK_SECRET_KEY")

    if fastapi_secret:
        if legacy_secret and legacy_secret != fastapi_secret:
            logger.warning(
                "Both FASTAPI_SECRET_KEY and FLASK_SECRET_KEY are set with "
                "different values. Using FASTAPI_SECRET_KEY."
            )
        return fastapi_secret

    if legacy_secret:
        logger.warning(
            "FLASK_SECRET_KEY is deprecated. Use FASTAPI_SECRET_KEY instead."
        )
        return legacy_secret

    return None


def get_session_same_site() -> str:
    # 本番では OAuth 戻りの互換性を優先して None を既定にし、
    # 明示設定時は妥当な SameSite 値のみ受け付ける。
    # Default to None in production for OAuth compatibility, while validating overrides.
    configured = (os.getenv("FASTAPI_SESSION_SAMESITE") or "").strip().lower()
    if not configured:
        return "none" if is_production_env() else "lax"

    if configured not in VALID_SESSION_SAMESITE_VALUES:
        logger.warning(
            "Invalid FASTAPI_SESSION_SAMESITE=%r. Falling back to the environment default.",
            configured,
        )
        return "none" if is_production_env() else "lax"

    if configured == "none" and not is_production_env():
        logger.warning(
            "FASTAPI_SESSION_SAMESITE=none requires HTTPS. Falling back to 'lax' outside production."
        )
        return "lax"

    return configured
