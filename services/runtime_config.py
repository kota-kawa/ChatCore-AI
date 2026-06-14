import logging
import os

logger = logging.getLogger(__name__)

VALID_SESSION_SAMESITE_VALUES = {"lax", "strict", "none"}


# 現在の実行環境（FASTAPI_ENVまたはFLASK_ENV）を取得し、無効な場合は'development'を返す
# Get the current runtime environment, prioritizing FASTAPI_ENV, and fallback to 'development'.
# 日本語: get runtime env の取得処理を担当します。
# English: Handle fetching for get runtime env.
def get_runtime_env() -> str:
    # 新環境変数を優先しつつ、旧変数も後方互換として受け付ける
    # Prefer the new env var while keeping legacy fallback for compatibility.
    runtime_env = os.getenv("FASTAPI_ENV")
    legacy_env = os.getenv("FLASK_ENV")

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if runtime_env:
        if legacy_env and legacy_env != runtime_env:
            logger.warning(
                "Both FASTAPI_ENV and FLASK_ENV are set with different values. "
                "Using FASTAPI_ENV."
            )
        return runtime_env

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if legacy_env:
        logger.warning("FLASK_ENV is deprecated. Use FASTAPI_ENV instead.")
        return legacy_env

    return "development"


# 現在の実行環境が本番環境（production）であるかどうかを判定する
# Determine whether the current runtime environment is the production environment.
# 日本語: is production env に関する処理の入口です。
# English: Entry point for logic related to is production env.
def is_production_env() -> bool:
    # 環境文字列比較はここに集約して呼び出し側の分岐を簡潔に保つ
    # Centralize environment check so call sites stay simple.
    return get_runtime_env().lower() == "production"


# セッション署名キーを環境変数（FASTAPI_SECRET_KEYまたはFLASK_SECRET_KEY）から取得する
# Retrieve the session secret key from environment variables.
# 日本語: get session secret key の取得処理を担当します。
# English: Handle fetching for get session secret key.
def get_session_secret_key() -> str | None:
    # セッション署名キーも FASTAPI_* を優先し、FLASK_* はレガシー互換として扱う
    # Resolve session secret with FASTAPI_* priority and FLASK_* legacy fallback.
    fastapi_secret = os.getenv("FASTAPI_SECRET_KEY")
    legacy_secret = os.getenv("FLASK_SECRET_KEY")

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if fastapi_secret:
        if legacy_secret and legacy_secret != fastapi_secret:
            logger.warning(
                "Both FASTAPI_SECRET_KEY and FLASK_SECRET_KEY are set with "
                "different values. Using FASTAPI_SECRET_KEY."
            )
        return fastapi_secret

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if legacy_secret:
        logger.warning(
            "FLASK_SECRET_KEY is deprecated. Use FASTAPI_SECRET_KEY instead."
        )
        return legacy_secret

    return None


# クッキーのSameSite属性の設定値を取得・バリデーションする
# Retrieve and validate the SameSite attribute configuration for cookies.
# 日本語: get session same site の取得処理を担当します。
# English: Handle fetching for get session same site.
def get_session_same_site() -> str:
    # SameSite=Lax を既定にして、フレーム内やサブリソースのクロスサイト送信を抑える。
    # Default to SameSite=Lax to avoid cross-site iframe/subresource session sends.
    configured = (os.getenv("FASTAPI_SESSION_SAMESITE") or "").strip().lower()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not configured:
        return "lax"

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
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
