from __future__ import annotations

from typing import Any

from services.cache import get_redis_client, is_redis_configured
from services.db import session_scope
from services.embeddings import get_embedding_health
from services.repositories.health_repository import HealthRepository


# サービスの生存（Liveness）状態を示すステータスを返します。基本的に常に "ok" を返します。
# Return the liveness status of the service. Always returns "ok" as a baseline.
def get_liveness_status() -> dict[str, Any]:
    return {"status": "ok"}


# データベースやRedisの接続状態を確認し、アプリがリクエストを受け入れ可能かを示す準備（Readiness）状態を返します。
# Check database and Redis connections and return the readiness status of the application.
async def get_readiness_status() -> tuple[dict[str, Any], int]:
    components: dict[str, dict[str, Any]] = {}
    overall_ok = True
    degraded = False

    # データベースへの接続と基本的なテーブルへのアクセスを試行し、接続状態とスキーマの健全性を確認します。
    # Attempt database connection and verify access to key tables to ensure schema health.
    try:
        async with session_scope() as session:
            # Check both connectivity and a core mapped table.  The query is
            # intentionally tiny so readiness never consumes a long-lived
            # application transaction.
            await HealthRepository(session).check_database()
        components["database"] = {"status": "ok", "required": True}
    except Exception as exc:
        overall_ok = False
        components["database"] = {
            "status": "error",
            "required": True,
            "detail": exc.__class__.__name__,
        }

    # Redisが設定されている場合、Redisへの接続状況を確認します。
    # If Redis is configured, verify the connection status to Redis.
    if is_redis_configured():
        redis_client = get_redis_client()
        if redis_client is None:
            degraded = True
            components["redis"] = {
                "status": "degraded",
                "required": False,
            }
        else:
            components["redis"] = {"status": "ok", "required": False}
    else:
        components["redis"] = {
            "status": "disabled",
            "required": False,
        }

    # 埋め込みが落ちるとメモ／マイコンテキスト検索が黙って部分一致へ劣化するため、
    # 必須ではないがreadinessに出して気付けるようにする。
    # A broken embedding provider silently degrades memo / My Context search to substring
    # matching, so surface it here even though it is not a required component.
    embedding_component = get_embedding_health()
    components["embeddings"] = embedding_component
    if embedding_component["status"] in {"degraded", "error"}:
        degraded = True

    if overall_ok:
        if degraded:
            return {"status": "degraded", "components": components}, 200
        return {"status": "ok", "components": components}, 200
    return {"status": "error", "components": components}, 503
