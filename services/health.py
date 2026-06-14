from __future__ import annotations

from typing import Any

from services.cache import get_redis_client, is_redis_configured
from services.db import get_db_connection


# サービスの生存（Liveness）状態を示すステータスを返す。基本的に常に "ok" を返す。
# Return the liveness status of the service. Always returns "ok" as a baseline.
# 日本語: get liveness status の取得処理を担当します。
# English: Handle fetching for get liveness status.
def get_liveness_status() -> dict[str, Any]:
    return {"status": "ok"}


# データベースやRedisの接続状態を確認し、アプリがリクエストを受け入れ可能かを示す準備（Readiness）状態を返す。
# Check database and Redis connections and return the readiness status of the application.
# 日本語: get readiness status の取得処理を担当します。
# English: Handle fetching for get readiness status.
def get_readiness_status() -> tuple[dict[str, Any], int]:
    components: dict[str, dict[str, Any]] = {}
    overall_ok = True
    degraded = False

    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                cursor.close()
        components["database"] = {"status": "ok", "required": True}
    except Exception as exc:
        overall_ok = False
        components["database"] = {
            "status": "error",
            "required": True,
            "detail": exc.__class__.__name__,
        }

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
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

    if overall_ok:
        if degraded:
            return {"status": "degraded", "components": components}, 200
        return {"status": "ok", "components": components}, 200
    return {"status": "error", "components": components}, 503
