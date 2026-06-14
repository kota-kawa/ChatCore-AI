# app.py
import logging
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import asynccontextmanager
from datetime import timedelta

from dotenv import load_dotenv

# アプリケーションモジュールをインポートする前に環境変数を読み込む。
# .env.local が存在すれば .env の値を上書きする（ローカル開発用設定として使用）。
# Load env vars before importing application modules so that module-level
# constants (e.g. FRONTEND_URL in web_constants.py) pick up the correct values.
# .env.local overrides .env and is intended for local-development overrides.
load_dotenv()
load_dotenv(".env.local", override=True)

from fastapi import FastAPI, Request  # noqa: E402

from blueprints.chat import cleanup_ephemeral_chats  # noqa: E402
from services.auth_limits import AuthLimitService  # noqa: E402
from services.chat_generation import ChatGenerationService  # noqa: E402
from services.background_executor import (  # noqa: E402
    shutdown_background_executor,
    submit_background_task,
)
from services.db import close_db_pool  # noqa: E402
from services.default_tasks import ensure_default_tasks_seeded  # noqa: E402
from services.default_shared_prompts import ensure_default_shared_prompts  # noqa: E402
from services.health import get_liveness_status, get_readiness_status  # noqa: E402
from services.llm_daily_limit import LlmDailyLimitService  # noqa: E402
from services.logging_config import configure_logging  # noqa: E402
from services.csrf import get_or_create_csrf_token  # noqa: E402
from services.request_context import RequestContextMiddleware  # noqa: E402
from services.runtime_config import (  # noqa: E402
    get_session_same_site,
    get_session_secret_key,
    is_production_env,
)
from services.security_headers import SecurityHeadersMiddleware  # noqa: E402
from services.session_middleware import PermanentSessionMiddleware  # noqa: E402
from services.web import DEFAULT_INTERNAL_ERROR_MESSAGE, jsonify  # noqa: E402

# ルートロガーにコンソール+ローテーションファイル出力を設定する
# Configure console + rotating file logging on the root logger.
configure_logging()
logger = logging.getLogger(__name__)

# セッション署名キーは起動時に必須チェックし、不足時は即時停止する
# Validate session secret at boot and fail fast when it is missing.
secret_key = get_session_secret_key()
if not secret_key:
    raise ValueError(
        "No session secret key set. Define FASTAPI_SECRET_KEY "
        "(or legacy FLASK_SECRET_KEY)."
    )
permanent_max_age = int(timedelta(days=30).total_seconds())

# SameSite は環境に応じて切り替え、HTTPS の時のみ Secure を有効化する
# Select SameSite by runtime environment and enable Secure only on HTTPS deployments.
same_site = get_session_same_site()
https_only = is_production_env()


# 一時的なチャットデータを定期的にクリーンアップするバックグラウンドタスク
# A background task to periodically clean up ephemeral chat data
def periodic_cleanup(stop_event: threading.Event) -> None:
    # 停止イベントがセットされるまでループを実行
    # Run the loop until the stop event is set
    while not stop_event.is_set():
        try:
            # 一時チャットの削除処理を呼び出す
            # Call the handler to delete ephemeral chats
            cleanup_ephemeral_chats()
        except Exception:
            logger.exception("Failed to clean up ephemeral chats.")
        # 100分（6000秒）待機するか、停止イベントの発生を待つ
        # Wait for 100 minutes (6000 seconds) or until the stop event is signaled
        stop_event.wait(timeout=6000)


# アプリケーションの起動時とシャットダウン時のライフサイクルイベントを管理する
# Manage startup and shutdown lifecycle events of the FastAPI application.
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # 起動時の処理: デフォルトタスクや初期プロンプトのDB登録
    # Startup processing: Seeding default tasks and initial shared prompts
    try:
        # デフォルトタスクの初期データをデータベースに投入する（未投入分のみ）
        # Seed default tasks into the database (insert only missing rows)
        inserted = ensure_default_tasks_seeded()
        if inserted > 0:
            logger.info("Seeded %s default tasks.", inserted)
    except Exception:
        logger.exception("Failed to seed default tasks.")
        raise

    try:
        # 共有の初期プロンプトデータをデータベースに投入する（未投入分のみ）
        # Seed sample shared prompts into the database (insert only missing rows)
        inserted = ensure_default_shared_prompts()
        if inserted > 0:
            logger.info("Seeded %s sample shared prompts.", inserted)
    except Exception:
        logger.exception("Failed to seed sample shared prompts.")
        raise

    # クリーンアップタスク用の停止シグナルイベントを作成
    # Create a stop signal event for the periodic cleanup task
    cleanup_stop_event = threading.Event()
    # バックグラウンドスレッドで一時チャットのクリーンアップを開始
    # Start the ephemeral chat cleanup task in a background thread
    cleanup_future = submit_background_task(periodic_cleanup, cleanup_stop_event)

    try:
        # アプリケーションが実行中の状態となる
        # Application runs and serves requests
        yield
    finally:
        # シャットダウン時の処理: 各種リソースやスレッドの安全なクリーンアップ
        # Shutdown processing: Safe cleanup of active resources and worker threads
        shutdown_wait_safe = True
        
        # チャット生成サービスのインメモリ状態をリセットし、実行中のジョブをキャンセルする
        # Reset in-memory state of the chat generation service and cancel running jobs
        chat_generation_service = getattr(app_instance.state, "chat_generation_service", None)
        if isinstance(chat_generation_service, ChatGenerationService):
            chat_generation_service.reset_in_memory_state(cancel_running=True)
            # ジョブが正常に終了するのを最大5秒待機する
            # Wait up to 5 seconds for active generation jobs to finish
            jobs_stopped = chat_generation_service.wait_for_running_jobs(timeout=5.0)
            if not jobs_stopped:
                shutdown_wait_safe = False
                logger.warning("Timed out while waiting for chat generation jobs to finish.")
        
        # バックグラウンドのクリーンアップタスクを停止する
        # Stop the background cleanup task
        cleanup_stop_event.set()
        try:
            # クリーンアップタスクのスレッド終了を最大5秒待機する
            # Wait up to 5 seconds for the cleanup task thread to exit
            cleanup_future.result(timeout=5.0)
        except FutureTimeoutError:
            shutdown_wait_safe = False
            logger.warning("Timed out while waiting for periodic cleanup to stop.")
        except Exception:
            logger.exception("Periodic cleanup worker exited with an unexpected error.")
        
        # バックグラウンドタスク実行用のスレッドプールをシャットダウンする
        # Shutdown the background task executor pool
        shutdown_background_executor(
            wait=shutdown_wait_safe,
            cancel_futures=not shutdown_wait_safe,
        )
        # データベース接続プールを閉じる
        # Close the database connection pool
        close_db_pool()


# FastAPIアプリケーションの初期化とサービスの登録
# Initialize FastAPI application and register global services
app = FastAPI(lifespan=lifespan)
app.state.auth_limit_service = AuthLimitService()
app.state.llm_daily_limit_service = LlmDailyLimitService()
app.state.chat_generation_service = ChatGenerationService()

# セッション管理、コンテキスト管理、セキュリティヘッダー付与用のミドルウェアを設定
# Register middlewares for session handling, request context, and security headers
app.add_middleware(
    PermanentSessionMiddleware,
    secret_key=secret_key,
    session_cookie="session",
    max_age=permanent_max_age,
    same_site=same_site,
    https_only=https_only,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# ミドルウェア設定値をアプリケーション状態に保存
# Store session settings in the application state
app.state.session_secret = secret_key
app.state.session_cookie = "session"


# 新しいCSRFトークンを生成、または既存のトークンを取得してクライアントに返却する
# Generate a new CSRF token or retrieve an existing one, then return it to the client.
@app.get("/api/csrf-token")
async def issue_csrf_token(request: Request):
    # CSRFトークンを取得、または新規生成してJSONで返却
    # Retrieve or generate CSRF token and return as JSON
    token = get_or_create_csrf_token(request)
    return jsonify({"csrf_token": token})


# アプリケーションの生存状態（Liveness）を確認するためのエンドポイント
# Endpoint for checking the liveness status of the application.
@app.get("/healthz")
async def healthz():
    # 生存状態チェック結果をJSONで返却
    # Return the liveness check result as JSON
    return jsonify(get_liveness_status())


# アプリケーションの準備状態（Readiness）を確認するためのエンドポイント
# Endpoint for checking the readiness status of the application.
@app.get("/readyz")
async def readyz():
    # 接続先DBや各種サービスのステータスを含む準備状態をJSONで返却
    # Return the readiness check results and corresponding HTTP status code
    payload, status_code = get_readiness_status()
    return jsonify(payload, status_code=status_code)


# 各 Router を読み込んでエンドポイント定義を登録可能にする
# Import routers so endpoint definitions are attached.
from blueprints.auth import auth_bp  # noqa: E402
from blueprints.verification import verification_bp  # noqa: E402
from blueprints.chat import chat_bp  # noqa: E402
from blueprints.prompt_share import prompt_share_bp  # noqa: E402
from blueprints.prompt_share.prompt_share_api import prompt_share_api_bp  # noqa: E402
from blueprints.prompt_share.prompt_search import search_bp  # noqa: E402
from blueprints.prompt_share.prompt_manage_api import prompt_manage_api_bp  # noqa: E402
from blueprints.admin import admin_bp  # noqa: E402
from blueprints.memo import memo_bp  # noqa: E402

# ルーティングテーブルに各 Router を登録する
# Register all routers into the app routing table.
app.include_router(auth_bp)
app.include_router(verification_bp)
app.include_router(chat_bp)
app.include_router(prompt_share_bp)
app.include_router(prompt_share_api_bp)
app.include_router(search_bp)
app.include_router(prompt_manage_api_bp)
app.include_router(admin_bp)
app.include_router(memo_bp)


# キャッチされなかった例外を処理し、安全なエラーレスポンスを返却するグローバル例外ハンドラー
# Global exception handler to catch unhandled exceptions and return a safe error response.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # エラー内容をログ出力し、一般的なエラーメッセージを返却
    # Log the full exception trace and return a generic internal error message
    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return jsonify({"error": DEFAULT_INTERNAL_ERROR_MESSAGE}, status_code=500)


# アプリケーションを直接実行する場合のエントリーポイント
if __name__ == "__main__":
    import uvicorn

    # ポート番号を取得し、Uvicornサーバーを起動
    # Get port configuration from environment variables and start the Uvicorn server
    port = int(os.getenv("PORT", "5004"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
