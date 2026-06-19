# prompt_manage_api.py
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import get_db_connection
from services.prompt_types import serialize_axes
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


# いいね済みプロンプト行を標準JSON形式にシリアライズする関数
# Serialize liked prompt rows for the API response.
def _serialize_liked_prompt(row: dict[str, Any]) -> dict[str, Any]:
    """
    DBのいいねレコードと公開プロンプト情報を、設定画面用のAPIレスポンス形式に整形する。
    Serialize a liked prompt database row to the standardized settings API response format.
    """
    # 日付フィールドのISO 8601フォーマットへのシリアライズ処理を行う
    # Parse and convert datetime fields to ISO 8601 format strings.
    prompt_created_at = row.get("prompt_created_at")
    liked_at = row.get("liked_at")
    return {
        "id": row.get("like_id"),
        "like_id": row.get("like_id"),
        "prompt_id": row.get("prompt_id"),
        "title": row.get("title"),
        "category": row.get("category"),
        "content": row.get("content"),
        "author": row.get("author"),
        # 2軸フィールド＋後方互換の派生フィールドを付与する。
        # Attach the two-axis fields plus derived legacy fields.
        **serialize_axes(row),
        "input_examples": row.get("input_examples"),
        "output_examples": row.get("output_examples"),
        "prompt_created_at": (
            prompt_created_at.isoformat()
            if hasattr(prompt_created_at, "isoformat")
            else prompt_created_at
        ),
        "created_at": (
            prompt_created_at.isoformat()
            if hasattr(prompt_created_at, "isoformat")
            else prompt_created_at
        ),
        "liked_at": liked_at.isoformat() if hasattr(liked_at, "isoformat") else liked_at,
        "liked": True,
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
                    content_format,
                    media_type,
                    attributes,
                    attachments,
                    created_at
                FROM prompts
                WHERE user_id = %s
                  AND deleted_at IS NULL
                ORDER BY created_at DESC
            """
            cursor.execute(query, (user_id,))
            # 2軸フィールドを正準化し、後方互換の派生フィールドを付与する。
            # Normalize the two-axis fields and attach derived legacy fields.
            return [{**dict(row), **serialize_axes(dict(row))} for row in cursor.fetchall()]
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


# ユーザーがいいねしたプロンプト一覧をDBから取得する関数
# Database lookup to retrieve prompts liked by the user.
def _fetch_liked_prompts(user_id: int) -> list[dict[str, Any]]:
    """
    ユーザーがいいねした公開中プロンプト一覧を、関連するプロンプト詳細及びユーザー情報とJOINしてDBから取得する。
    Retrieve public prompts liked by the user, joined with prompt and user details, and return serialized records.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # いいねされた公開プロンプト情報と投稿者名をJOINで取得
            # Fetch liked public prompt details joined with author name.
            query = """
                SELECT pl.id AS like_id,
                       pl.prompt_id,
                       p.title,
                       p.category,
                       p.content,
                       COALESCE(u.username, p.author, 'ユーザー') AS author,
                       p.content_format,
                       p.media_type,
                       p.attributes,
                       p.attachments,
                       p.input_examples,
                       p.output_examples,
                       p.created_at AS prompt_created_at,
                       pl.created_at AS liked_at
                FROM prompt_likes pl
                JOIN prompts p ON p.id = pl.prompt_id
                              AND p.is_public = TRUE
                              AND p.deleted_at IS NULL
                LEFT JOIN users u ON u.id = p.user_id
                WHERE pl.user_id = %s
                ORDER BY pl.created_at DESC, pl.id DESC
            """
            cursor.execute(query, (user_id,))
            # 取得レコードをループ処理してAPI用フォーマットにシリアライズ
            # Serialize each fetched database row to the standard API structure.
            return [_serialize_liked_prompt(dict(row)) for row in cursor.fetchall()]
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


# ログインユーザーがいいねしたプロンプト一覧を取得するエンドポイント
# Endpoint to get prompts liked by the authenticated user.
@prompt_manage_api_bp.get("/liked_prompts", name="prompt_manage_api.get_liked_prompts")
async def get_liked_prompts(request: Request):
    """
    ログイン中のユーザーがいいねした公開プロンプト一覧をJSON形式で返却する。
    GET API to retrieve the list of public prompts liked by the logged-in user.
    """
    # セッションのログイン有無を検証
    # Check if the user is authenticated.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        # 非ブロッキングスレッドプールでDB処理を実行
        # Run database operation in a separate thread.
        prompts = await run_blocking(_fetch_liked_prompts, user_id)
        return jsonify({"prompts": prompts})
    except Exception:
        # エラーログ出力と500レスポンス返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to load liked prompts.",
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
