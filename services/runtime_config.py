import logging
import os

logger = logging.getLogger(__name__)

# 日本語: 有効なSameSite属性の設定値セット。
# English: Set of valid SameSite attribute values.
VALID_SESSION_SAMESITE_VALUES = {"lax", "strict", "none"}


# 日本語: 現在の実行環境（FASTAPI_ENVまたはFLASK_ENV）を取得し、無効な場合は'development'を返します。
# English: Get the current runtime environment, prioritizing FASTAPI_ENV, and fallback to 'development'.
def get_runtime_env() -> str:
    # 日本語: 新環境変数を優先しつつ、旧変数も後方互換として受け付けます。
    # English: Prefer the new env var while keeping legacy fallback for compatibility.
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


# 日本語: 現在の実行環境が本番環境（production）であるかどうかを判定します。
# English: Determine whether the current runtime environment is the production environment.
def is_production_env() -> bool:
    # 日本語: 環境文字列比較はここに集約して呼び出し側の分岐を簡潔に保ちます。
    # English: Centralize environment check so call sites stay simple.
    return get_runtime_env().lower() == "production"


# 日本語: セッション署名キーを環境変数（FASTAPI_SECRET_KEYまたはFLASK_SECRET_KEY）から取得します。
# English: Retrieve the session secret key from environment variables.
def get_session_secret_key() -> str | None:
    # 日本語: セッション署名キーも FASTAPI_* を優先し、FLASK_* はレガシー互換として扱います。
    # English: Resolve session secret with FASTAPI_* priority and FLASK_* legacy fallback.
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


# 日本語: クッキーのSameSite属性の設定値を取得・バリデーションします。
# English: Retrieve and validate the SameSite attribute configuration for cookies.
def get_session_same_site() -> str:
    # 日本語: SameSite=Lax を既定にして、フレーム内やサブリソースのクロスサイト送信を抑えます。
    # English: Default to SameSite=Lax to avoid cross-site iframe/subresource session sends.
    configured = (os.getenv("FASTAPI_SESSION_SAMESITE") or "").strip().lower()
    if not configured:
        return "lax"

    if configured not in VALID_SESSION_SAMESITE_VALUES:
        logger.warning(
            "Invalid FASTAPI_SESSION_SAMESITE=%r. Falling back to the environment default.",
            configured,
        )
        return "lax"

    if configured == "none" and not is_production_env():
        logger.warning(
            "FASTAPI_SESSION_SAMESITE=none requires HTTPS. Falling back to 'lax' outside production."
        )
        return "lax"

    return configured
