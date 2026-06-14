from __future__ import annotations

import json
import logging
import sys

from services.background_executor import get_background_executor
from services.db import get_db_connection as default_get_db_connection
from services.memo_ai import (
    build_memo_embedding_text,
    embeddings_available,
    generate_embedding,
)

logger = logging.getLogger("blueprints.memo")


# メモモジュールから動的にDB接続取得関数を解決するヘルパー（循環参照防止）
# Helper to dynamically retrieve the DB connection function to avoid circular imports.
def _get_db_connection():
    memo_module = sys.modules.get("blueprints.memo")
    if memo_module is not None:
        return getattr(memo_module, "get_db_connection", default_get_db_connection)()
    return default_get_db_connection()


# 生成された埋め込みベクトルをデータベースに保存する関数
# Save the generated embedding vector into the database.
def store_embedding(memo_id: int, embedding: list[float]) -> None:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()
        # ベクトルデータをJSON形式の文字列にシリアライズして保存
        # Serialize the vector array to a JSON string and store it.
        cursor.execute(
            "UPDATE memo_entries SET embedding = %s WHERE id = %s",
            (json.dumps(embedding), memo_id),
        )
        connection.commit()
    except Exception:
        # エラー発生時は警告ログを出力し処理を継続
        # Log a warning on failure and continue execution.
        logger.warning("Failed to store embedding for memo %s", memo_id, exc_info=True)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# 指定されたメモの埋め込みベクトル生成処理を非同期でバックグラウンド実行するスケジュール関数
# Schedule a background task to generate and store the vector embedding for a memo.
def schedule_embedding(memo_id: int, title: str, ai_response: str) -> None:
    # 埋め込みモデル/APIが有効でない場合は何もしない
    # Do nothing if embeddings support is not available.
    if not embeddings_available():
        return

    # バックグラウンド実行される内部タスク関数
    # Internal task function executed in the background.
    def _task() -> None:
        # 埋め込み用の結合テキストを作成
        # Construct the unified text sequence for embedding.
        text = build_memo_embedding_text(title, ai_response)
        
        # 埋め込みベクトルを生成
        # Generate embedding vector.
        embedding = generate_embedding(text)
        
        # ベクトルが正常生成できればDBに保存
        # If successfully generated, store in database.
        if embedding:
            store_embedding(memo_id, embedding)

    try:
        # バックグラウンドエグゼキューターにタスクを登録
        # Submit the task to the background executor.
        get_background_executor().submit(_task)
    except Exception:
        # スケジュール登録失敗時のログ出力
        # Log a warning on task submission failure.
        logger.warning("Failed to schedule embedding task for memo %s", memo_id, exc_info=True)
