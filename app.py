# app.py
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import timedelta

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from blueprints.chat import cleanup_ephemeral_chats
from services.db import close_db_pool
from services.default_tasks import ensure_default_tasks_seeded
from services.default_shared_prompts import ensure_default_shared_prompts
from services.health import get_liveness_status, get_readiness_status
from services.logging_config import configure_logging
from services.csrf import get_or_create_csrf_token
from services.request_context import RequestContextMiddleware
from services.runtime_config import (
    get_session_same_site,
    get_session_secret_key,
    is_production_env,
)
from services.session_middleware import PermanentSessionMiddleware
from services.web import DEFAULT_INTERNAL_ERROR_MESSAGE, jsonify

# 初回起動時に環境変数を読み込む
# Load environment variables at startup.
load_dotenv()

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


def periodic_cleanup(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            cleanup_ephemeral_chats()
        except Exception:
            logger.exception("Failed to clean up ephemeral chats.")
        # 停止シグナルまで定期的にエフェメラルチャットをクリーンアップする
        # Keep cleaning ephemeral chats periodically until stop is requested.
        stop_event.wait(timeout=6000)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 起動時にデフォルトタスクを投入する（未投入分のみ）
    # Seed default tasks on startup (insert only missing rows).
    try:
        inserted = ensure_default_tasks_seeded()
        if inserted > 0:
            logger.info("Seeded %s default tasks.", inserted)
    except Exception:
        logger.exception("Failed to seed default tasks.")
        raise

    # 起動時に共有サンプルプロンプトを投入する（未投入分のみ）
    # Seed sample shared prompts on startup (insert only missing rows).
    try:
        inserted = ensure_default_shared_prompts()
        if inserted > 0:
            logger.info("Seeded %s sample shared prompts.", inserted)
    except Exception:
        logger.exception("Failed to seed sample shared prompts.")
        raise

    cleanup_stop_event = threading.Event()
    cleanup_thread = threading.Thread(
        target=periodic_cleanup,
        args=(cleanup_stop_event,),
        daemon=True,
        name="ephemeral-chat-cleanup",
    )
    cleanup_thread.start()

    try:
        yield
    finally:
        cleanup_stop_event.set()
        cleanup_thread.join(timeout=1)
        close_db_pool()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    PermanentSessionMiddleware,
    secret_key=secret_key,
    session_cookie="session",
    max_age=permanent_max_age,
    same_site=same_site,
    https_only=https_only,
)
app.add_middleware(RequestContextMiddleware)

app.state.session_secret = secret_key
app.state.session_cookie = "session"


@app.get("/api/csrf-token")
async def issue_csrf_token(request: Request):
    token = get_or_create_csrf_token(request)
    return jsonify({"csrf_token": token})


@app.get("/healthz")
async def healthz():
    return jsonify(get_liveness_status())


@app.get("/readyz")
async def readyz():
    payload, status_code = get_readiness_status()
    return jsonify(payload, status_code=status_code)


# 各 Router を読み込んでエンドポイント定義を登録可能にする
# Import routers so endpoint definitions are attached.
from blueprints.auth import auth_bp
from blueprints.verification import verification_bp
from blueprints.chat import chat_bp
from blueprints.prompt_share import prompt_share_bp
from blueprints.prompt_share.prompt_share_api import prompt_share_api_bp
from blueprints.prompt_share.prompt_search import search_bp
from blueprints.prompt_share.prompt_manage_api import prompt_manage_api_bp
from blueprints.admin import admin_bp
from blueprints.memo import memo_bp

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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return jsonify({"error": DEFAULT_INTERNAL_ERROR_MESSAGE}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "5004"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
