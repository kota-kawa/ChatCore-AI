# prompt_manage_api.py
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import get_db_connection
from services.request_models import PromptUpdateRequest
from services.web import (
    jsonify,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

# CSRF保護を設定したプロンプト管理用APIRouterの初期化
# Initialize FastAPI APIRouter for prompt management with CSRF protection.
prompt_manage_api_bp = APIRouter(prefix="/prompt_manage/api", dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)


# ブックマーク保存されたプロンプトエントリ行を標準JSON形式にシリアライズする関数
# Serialize bookmark saved prompt list entry records for the API response.
def _serialize_prompt_list_entry(row: dict[str, Any]) -> dict[str, Any]:
    """
    DBのブックマーク（プロンプトリスト）エントリレコードをシリアライズして標準のAPIレスポンス形式にする。
    Serialize a database prompt list entry row to the standardized API response format.
    """
    # 日付フィールドのISO 8601フォーマットへのシリアライズ処理を行う
    # Parse and convert datetime fields to ISO 8601 format strings.
    prompt_created_at = row.get("prompt_created_at")
    saved_at = row.get("saved_at")
    return {
        "id": row.get("entry_id"),
        "prompt_id": row.get("prompt_id"),
        "created_at": saved_at.isoformat() if hasattr(saved_at, "isoformat") else saved_at,
        "prompt": {
            "id": row.get("prompt_id"),
            "title": row.get("title"),
            "category": row.get("category"),
            "content": row.get("content"),
            "author": row.get("author"),
            "prompt_type": row.get("prompt_type") or "text",
            "reference_image_url": row.get("reference_image_url"),
            "skill_markdown": row.get("skill_markdown") or "",
            "skill_python_script": row.get("skill_python_script") or "",
            "input_examples": row.get("input_examples"),
            "output_examples": row.get("output_examples"),
            "created_at": (
                prompt_created_at.isoformat()
                if hasattr(prompt_created_at, "isoformat")
                else prompt_created_at
            ),
        },
    }


# ユーザー自身が投稿・公開したプロンプト一覧をDBから取得する関数
# Database lookup to fetch prompts submitted/published by the authenticated user.
def _fetch_my_prompts(user_id: int) -> list[dict[str, Any]]:
    """
    指定されたユーザーIDが作成した、削除されていない公開プロンプトの一覧をDBから取得する。
    Retrieve all non-deleted public prompts authored by the specified user ID from the database.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # ユーザー作成プロンプトを最新の作成日時順で取得
            # Fetch prompts created by the user, ordered by creation time descending.
            query = """
                SELECT
                    id,
                    title,
                    category,
                    content,
                    input_examples,
                    output_examples,
                    prompt_type,
                    reference_image_url,
                    skill_markdown,
                    skill_python_script,
                    created_at
                FROM prompts
                WHERE user_id = %s
                  AND deleted_at IS NULL
                ORDER BY created_at DESC
            """
            cursor.execute(query, (user_id,))
            return cursor.fetchall()
        finally:
            # カーソルを確実にクローズ
            # Ensure the cursor is closed properly.
            cursor.close()


# ユーザーが自身のタスク一覧として追加・保存したプロンプトをDBから取得する関数
# Database lookup to fetch templates added as tasks by the user.
def _fetch_saved_prompts(user_id: int) -> list[dict[str, Any]]:
    """
    ユーザーが自身のタスクテンプレート（入力例・出力例付き）として保存したプロンプト一覧をDBから取得する。
    Retrieve task templates with examples saved by the user from the database.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # 論理削除されていないタスクテンプレートを取得
            # Fetch non-deleted task templates, sorted by creation date descending.
            query = """
                SELECT id,
                       name,
                       prompt_template,
                       response_rules,
                       output_skeleton,
                       input_examples,
                       output_examples,
                       created_at
                FROM task_with_examples
                WHERE user_id = %s
                  AND deleted_at IS NULL
                ORDER BY created_at DESC, id DESC
            """
            cursor.execute(query, (user_id,))
            return cursor.fetchall()
        finally:
            # カーソルを確実にクローズ
            # Ensure the cursor is closed properly.
            cursor.close()


# ユーザーがブックマーク保存（お気に入りリスト登録）したプロンプト一覧をDBから取得する関数
# Database lookup to retrieve the user's bookmarks (saved prompts list).
def _fetch_prompt_list(user_id: int) -> list[dict[str, Any]]:
    """
    ユーザーがブックマーク（お気に入りリスト）に保存したプロンプト一覧を、関連するプロンプト詳細及びユーザー情報とJOINしてDBから取得する。
    Retrieve prompt list entries saved by the user, joined with prompt and user details, and return serialized records.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # ブックマークされたプロンプト情報と投稿者名をJOINで取得
            # Fetch bookmarked prompt details joined with author's name.
            query = """
                SELECT ple.id AS entry_id,
                       ple.prompt_id,
                       p.title,
                       p.category,
                       p.content,
                       COALESCE(u.username, p.author, 'ユーザー') AS author,
                       p.prompt_type,
                       p.reference_image_url,
                       p.skill_markdown,
                       p.skill_python_script,
                       p.input_examples,
                       p.output_examples,
                       p.created_at AS prompt_created_at,
                       ple.created_at AS saved_at
                FROM prompt_list_entries ple
                JOIN prompts p ON p.id = ple.prompt_id
                              AND p.deleted_at IS NULL
                LEFT JOIN users u ON u.id = p.user_id
                WHERE ple.user_id = %s
                ORDER BY ple.created_at DESC, ple.id DESC
            """
            cursor.execute(query, (user_id,))
            # 取得レコードをループ処理してAPI用フォーマットにシリアライズ
            # Serialize each fetched database row to the standard API structure.
            return [_serialize_prompt_list_entry(dict(row)) for row in cursor.fetchall()]
        finally:
            # カーソルを確実にクローズ
            # Ensure the cursor is closed properly.
            cursor.close()


# ブックマーク保存リストから指定されたエントリを削除する関数
# Delete a specific bookmark list entry for a user.
def _delete_prompt_list_entry_for_user(user_id: int, entry_id: int) -> int:
    """
    指定されたエントリIDとユーザーIDに一致するブックマーク登録を削除する。
    Delete a specific bookmark list entry matching the given user ID and entry ID.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # ブックマークテーブルから直接物理削除を実行
            # Hard delete the entry directly from prompt_list_entries table.
            query = "DELETE FROM prompt_list_entries WHERE id = %s AND user_id = %s"
            cursor.execute(query, (entry_id, user_id))
            conn.commit()
            # 影響を受けた行数を返す
            # Return the count of affected rows.
            return cursor.rowcount
        finally:
            # カーソルを確実にクローズ
            # Ensure the cursor is closed properly.
            cursor.close()


# 保存済みタスクプロンプトをソフトデリート（論理削除）する関数
# Perform a soft delete (set deleted_at) on a user's saved task prompt template.
def _delete_saved_prompt_for_user(user_id: int, prompt_id: int) -> int:
    """
    ユーザーの保存済みタスクテンプレート(task_with_examples)を論理削除(deleted_at更新)する。
    Mark a saved task template as deleted (soft delete) for the specified user and prompt ID.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # deleted_atカラムに現在日時をセットして論理削除を行う
            # Soft delete the row by setting deleted_at to current timestamp.
            query = """
                UPDATE task_with_examples
                   SET deleted_at = CURRENT_TIMESTAMP
                 WHERE id = %s
                   AND user_id = %s
                   AND deleted_at IS NULL
            """
            cursor.execute(query, (prompt_id, user_id))
            conn.commit()
            # 影響を受けた行数を返す
            # Return the count of affected rows.
            return cursor.rowcount
        finally:
            # カーソルを確実にクローズ
            # Ensure the cursor is closed properly.
            cursor.close()


# 投稿したプロンプト属性を更新する関数
# Update a user's published prompt attributes in the database.
def _update_prompt_for_user(
    user_id: int,
    prompt_id: int,
    title: str,
    category: str,
    content: str,
    input_examples: str,
    output_examples: str,
) -> int:
    """
    ユーザーが投稿した公開プロンプトの内容（タイトル、カテゴリ、本文、入出力例など）を更新する。
    Update basic attributes of an existing prompt created by the authenticated user.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # タイトル、カテゴリ、本文、入出力例の変更を反映
            # Update title, category, content, input_examples, and output_examples columns.
            query = """
                UPDATE prompts
                SET title = %s, category = %s, content = %s, input_examples = %s, output_examples = %s
                WHERE id = %s
                  AND user_id = %s
                  AND deleted_at IS NULL
            """
            cursor.execute(
                query,
                (
                    title,
                    category,
                    content,
                    input_examples,
                    output_examples,
                    prompt_id,
                    user_id,
                ),
            )
            conn.commit()
            # 影響を受けた行数を返す
            # Return the count of affected rows.
            return cursor.rowcount
        finally:
            # カーソルを確実にクローズ
            # Ensure the cursor is closed properly.
            cursor.close()


# 投稿したプロンプトをソフトデリート（論理削除）する関数
# Soft delete a user's published prompt in the database.
def _delete_prompt_for_user(user_id: int, prompt_id: int) -> int:
    """
    ユーザーが投稿した公開プロンプト(prompts)を論理削除(deleted_at更新)する。
    Mark a published prompt as deleted (soft delete) for the specified user and prompt ID.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # deleted_atカラムに現在日時をセットして論理削除を行う
            # Soft delete the row by setting deleted_at to current timestamp.
            query = """
                UPDATE prompts
                   SET deleted_at = CURRENT_TIMESTAMP
                 WHERE id = %s
                   AND user_id = %s
                   AND deleted_at IS NULL
            """
            cursor.execute(query, (prompt_id, user_id))
            conn.commit()
            # 影響を受けた行数を返す
            # Return the count of affected rows.
            return cursor.rowcount
        finally:
            # カーソルを確実にクローズ
            # Ensure the cursor is closed properly.
            cursor.close()


# ログインユーザーが投稿したプロンプト一覧を取得するエンドポイント
# Endpoint to get list of prompts published by the authenticated user.
@prompt_manage_api_bp.get("/my_prompts", name="prompt_manage_api.get_my_prompts")
async def get_my_prompts(request: Request):
    """
    ログイン中のユーザーが投稿したプロンプトの一覧をJSON形式で返却する。
    GET API to retrieve the list of prompts published by the logged-in user.
    """
    # セッションのログイン有無を検証
    # Check if the user is authenticated.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]
    try:
        # 非ブロッキングスレッドプールでDB処理を実行
        # Run database operation in a separate thread.
        prompts = await run_blocking(_fetch_my_prompts, user_id)
        return jsonify({"prompts": prompts})
    except Exception:
        # エラーログ出力と500レスポンス返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to load my prompts.",
        )


# ログインユーザーがタスクとして追加したプロンプト一覧を取得するエンドポイント
# Endpoint to get list of templates saved as tasks by the authenticated user.
@prompt_manage_api_bp.get("/saved_prompts", name="prompt_manage_api.get_saved_prompts")
async def get_saved_prompts(request: Request):
    """
    ログイン中のユーザーがタスクとして保存したプロンプト一覧をJSON形式で返却する。
    GET API to retrieve the list of templates saved as tasks by the logged-in user.
    """
    # セッションのログイン有無を検証
    # Check if the user is authenticated.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        # 非ブロッキングスレッドプールでDB処理を実行
        # Run database operation in a separate thread.
        prompts = await run_blocking(_fetch_saved_prompts, user_id)
        return jsonify({"prompts": prompts})
    except Exception:
        # エラーログ出力と500レスポンス返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to load saved prompts.",
        )


# ログインユーザーのブックマーク保存されたプロンプト一覧を取得するエンドポイント
# Endpoint to get user's bookmarked prompt list.
@prompt_manage_api_bp.get("/prompt_list", name="prompt_manage_api.get_prompt_list")
async def get_prompt_list(request: Request):
    """
    ログイン中のユーザーがブックマーク（お気に入りリスト）に登録したプロンプト一覧をJSON形式で返却する。
    GET API to retrieve the list of bookmarked prompts for the logged-in user.
    """
    # セッションのログイン有無を検証
    # Check if the user is authenticated.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        # 非ブロッキングスレッドプールでDB処理を実行
        # Run database operation in a separate thread.
        prompts = await run_blocking(_fetch_prompt_list, user_id)
        return jsonify({"prompts": prompts})
    except Exception:
        # エラーログ出力と500レスポンス返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to load prompt list.",
        )


# 保存したブックマークプロンプトエントリを削除するエンドポイント
# Endpoint to delete a specific bookmarked prompt list entry.
@prompt_manage_api_bp.delete(
    "/prompt_list/{entry_id}", name="prompt_manage_api.delete_prompt_list_entry"
)
async def delete_prompt_list_entry(entry_id: int, request: Request):
    """
    ログイン中のユーザーのブックマークリストから指定のエントリIDを削除する。
    DELETE API to remove a specific bookmark list entry for the logged-in user.
    """
    # セッションのログイン有無を検証
    # Check if the user is authenticated.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        # 非ブロッキングスレッドプールでDB削除処理を実行
        # Run database delete operation in a separate thread.
        deleted = await run_blocking(_delete_prompt_list_entry_for_user, user_id, entry_id)
        if deleted == 0:
            # 削除対象が存在しなかった、または別ユーザーのエントリだった場合
            # Return 404 if the entry was not found or didn't belong to the user.
            return jsonify({"error": "対象のプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "プロンプトを削除しました。"})
    except Exception:
        # エラーログ出力と500レスポンス返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to delete prompt list entry.",
        )


# 保存したタスクプロンプトテンプレートを削除するエンドポイント
# Endpoint to delete a saved task template prompt.
@prompt_manage_api_bp.delete(
    "/saved_prompts/{prompt_id}", name="prompt_manage_api.delete_saved_prompt"
)
async def delete_saved_prompt(prompt_id: int, request: Request):
    """
    ログイン中のユーザーが保存したタスクテンプレートを削除（論理削除）する。
    DELETE API to soft-delete a saved task template prompt for the logged-in user.
    """
    # セッションのログイン有無を検証
    # Check if the user is authenticated.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        # 非ブロッキングスレッドプールでDB論理削除処理を実行
        # Run database update (soft-delete) in a separate thread.
        deleted = await run_blocking(_delete_saved_prompt_for_user, user_id, prompt_id)
        if deleted == 0:
            # 対象のレコードが見つからなかった、または別のユーザーのレコードだった場合
            # Return 404 if the saved prompt was not found or didn't belong to the user.
            return jsonify({"error": "対象の保存済みプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "保存したプロンプトを削除しました。"})
    except Exception:
        # エラーログ出力と500レスポンス返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to delete saved prompt.",
        )


# 投稿済みプロンプトの内容を更新するエンドポイント
# Endpoint to edit/update details of a prompt published by the user.
@prompt_manage_api_bp.put("/prompts/{prompt_id}", name="prompt_manage_api.update_prompt")
async def update_prompt(prompt_id: int, request: Request):
    """
    ログイン中のユーザーが投稿したプロンプトの詳細内容を更新する。
    PUT API to update details of a prompt published by the logged-in user.
    """
    # セッションのログイン有無を検証
    # Check if the user is authenticated.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]
    
    # リクエストデータがJSON辞書形式か検証
    # Retrieve and validate the JSON payload.
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # PromptUpdateRequestモデルを用いてバリデーション
    # Validate the data with the PromptUpdateRequest schema.
    payload, validation_error = validate_payload_model(
        data,
        PromptUpdateRequest,
        error_message="必要なフィールドが不足しています。",
    )
    if validation_error is not None:
        return validation_error

    try:
        # 非ブロッキングスレッドプールでDB更新処理を実行
        # Run database update in a separate thread.
        updated = await run_blocking(
            _update_prompt_for_user,
            user_id,
            prompt_id,
            payload.title,
            payload.category,
            payload.content,
            payload.input_examples,
            payload.output_examples,
        )
        if updated == 0:
            # 対象のプロンプトが存在しない、または別ユーザーの作成だった場合
            # Return 404 if the prompt was not found or didn't belong to the user.
            return jsonify({"error": "対象のプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "プロンプトが更新されました。"})
    except Exception:
        # エラーログ出力と500レスポンス返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to update prompt.",
        )


# 投稿済みプロンプトを削除するエンドポイント
# Endpoint to delete a published prompt.
@prompt_manage_api_bp.delete("/prompts/{prompt_id}", name="prompt_manage_api.delete_prompt")
async def delete_prompt(prompt_id: int, request: Request):
    """
    ログイン中のユーザーが投稿したプロンプトを削除（論理削除）する。
    DELETE API to soft-delete a published prompt for the logged-in user.
    """
    # セッションのログイン有無を検証
    # Check if the user is authenticated.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    try:
        # 非ブロッキングスレッドプールでDB論理削除処理を実行
        # Run database soft-delete in a separate thread.
        deleted = await run_blocking(_delete_prompt_for_user, user_id, prompt_id)
        if deleted == 0:
            # 対象のプロンプトが存在しない、または別ユーザーの作成だった場合
            # Return 404 if the prompt was not found or didn't belong to the user.
            return jsonify({"error": "対象のプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "プロンプトが削除されました。"})
    except Exception:
        # エラーログ出力と500レスポンス返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to delete prompt.",
        )
