from __future__ import annotations

import logging
import sys
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import Error
from services.error_messages import (
    ERROR_LOGIN_REQUIRED,
    ERROR_TOKEN_REQUIRED,
)
from services.request_models import (
    MemoBulkActionRequest,
    MemoCollectionCreateRequest,
    MemoCollectionUpdateRequest,
    MemoCreateRequest,
    MemoReorderRequest,
    MemoShareCreateRequest,
    MemoSuggestRequest,
    MemoToggleRequest,
    MemoUpdateRequest,
    ShareMemoRequest,
)
from services.web import (
    flash,
    get_json,
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
    redirect_to_frontend,
    require_json_dict,
    validate_payload_model,
)

from .constants import DEFAULT_MEMO_LIST_LIMIT, MAX_MEMO_LIST_LIMIT
from .helpers import user_id_from_session

# CSRF保護を設定したメモ機能用APIRouterの初期化
# Initialize FastAPI APIRouter for memo with CSRF protection.
memo_bp = APIRouter(prefix="/memo", dependencies=[Depends(require_csrf)])
logger = logging.getLogger("blueprints.memo")


def _memo_attr(name: str) -> Any:
    """
    メモモジュールから動的に属性を取得するヘルパー関数（循環参照防止）
    Helper to dynamically retrieve an attribute from the memo package to prevent circular imports.

    Args:
        name (str): 属性名 / Attribute name to retrieve.

    Returns:
        Any: 取得された属性 / The retrieved attribute.
    """
    return getattr(sys.modules["blueprints.memo"], name)


@memo_bp.get("/api/recent", name="memo.api_recent")
async def api_recent_memos(
    request: Request,
    limit: int = DEFAULT_MEMO_LIST_LIMIT,
    offset: int = 0,
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "manual",
    include_archived: bool = False,
    only_archived: bool = False,
    pinned_first: bool = True,
    collection_id: int | None = None,
):
    """
    メモ一覧をフィルターおよび並び替え条件に従って取得するエンドポイント
    Endpoint to retrieve recent memo summaries based on filters and sorting criteria.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request object.
        limit (int): 取得件数の上限値 / Maximum limit of items to retrieve.
        offset (int): 取得開始位置 / Offset starting position.
        q (str): 検索用キーワード / Search query string.
        date_from (str): 開始日の絞り込み / Filter starting date YYYY-MM-DD.
        date_to (str): 終了日の絞り込み / Filter ending date YYYY-MM-DD.
        sort (str): ソート順指定 / Sorting criteria identifier.
        include_archived (bool): アーカイブ済みメモを含めるか / Include archived memos in result.
        only_archived (bool): アーカイブ済みメモのみ取得するか / Fetch only archived memos.
        pinned_first (bool): ピン留めされたメモを優先するか / Prioritize pinned memos.
        collection_id (int | None): 特定コレクションで絞り込む場合のID / Filter by memo collection ID.

    Returns:
        Response: メモ一覧を含むJSONレスポンス / JSON response containing list of memos.
    """
    # セッションからログインユーザーのIDを取得。未ログインなら401を返却
    # Get user ID from session. Return 401 Unauthorized if not logged in.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # 取得件数とオフセットの安全な値（範囲内）を設定
    # Clamp limit and offset to safe ranges.
    safe_limit = max(1, min(limit, MAX_MEMO_LIST_LIMIT))
    safe_offset = max(0, offset)

    semantic_embedding: list[float] | None = None
    # セマンティック検索かつクエリが存在し、埋め込み機能が有効な場合、検索語句のベクトルを生成
    # If using semantic sort with a query, generate the query vector embedding if embeddings are enabled.
    if sort == "semantic" and q.strip() and _memo_attr("embeddings_available")():
        try:
            # 外部の埋め込み生成処理を実行
            # Generate vector embedding for the query.
            semantic_embedding = await run_blocking(_memo_attr("generate_embedding"), q.strip())
        except Exception:
            # ベクトル生成に失敗した場合は、テキスト検索にフォールバック
            # Log warning and fall back to regular text-based search.
            logger.warning("Failed to generate query embedding; falling back to text search.")

    try:
        # メモ一覧データをDBから取得
        # Fetch matching memo summaries from the database.
        result = await run_blocking(
            _memo_attr("_fetch_memo_summaries"),
            user_id,
            limit=safe_limit,
            offset=safe_offset,
            query=q,
            date_from=date_from,
            date_to=date_to,
            sort=sort if sort != "semantic" else "recent",
            include_archived=include_archived,
            only_archived=only_archived,
            pinned_first=pinned_first,
            collection_id=collection_id,
            semantic_query_embedding=semantic_embedding,
        )
        return jsonify(result)
    except Error:
        # DBエラー発生時は警告ログを出力し、空のリストを返却
        # Log DB error and fallback to returning an empty memo list.
        logger.warning("Failed to load memo summaries; returning an empty list.", exc_info=True)
        return jsonify({"memos": [], "total": 0})


@memo_bp.post("/api", name="memo.api_create")
async def api_create_memo(request: Request):
    """
    新規メモを作成して保存するエンドポイント
    Endpoint to create and save a new memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request object.

    Returns:
        Response: 保存結果および作成されたメモIDを含むJSONレスポンス / JSON response indicating creation success and memo ID.
    """
    # ユーザー認証の確認。未ログインなら401を返却
    # Verify user authentication. Return 401 Unauthorized if not logged in.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # リクエストデータ（JSONまたはフォームデータ）を取得して辞書化
    # Fetch request payload as JSON or fall back to form data.
    data = await get_json(request)
    if data is None:
        form = await request.form()
        data = {key: value for key, value in form.items()}
    if not isinstance(data, dict):
        data = {}

    # ペイロードモデルのバリデーションを実行
    # Validate request body format.
    payload, validation_error = validate_payload_model(
        data,
        MemoCreateRequest,
        error_message="AIの回答を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    # タイトルの自動決定（空の場合はAIレスポンスから抽出）
    # Automatically resolve title from AI response if not provided.
    resolved_title = _memo_attr("_ensure_title")(payload.ai_response, payload.title)
    try:
        # DBにメモを新規挿入
        # Insert the new memo into database.
        memo_id = await run_blocking(
            _memo_attr("_insert_memo"),
            user_id,
            payload.ai_response,
            resolved_title,
            payload.collection_id,
            payload.background_color,
        )
        # 成功メッセージをフラッシュセッションに格納
        # Store success message in session flash.
        flash(request, "メモを保存しました。", "success")

        # セマンティック検索用の埋め込みベクトル生成タスクをスケジュール
        # Schedule the vector embedding generation task for semantic search.
        if memo_id:
            _memo_attr("_schedule_embedding")(memo_id, resolved_title, payload.ai_response, 1)
        return jsonify({"status": "success", "memo_id": memo_id})
    except Error:
        # DB登録エラー時の共通エラーハンドリング
        # Handle database insertion error and return 500 status.
        return log_and_internal_server_error(logger, "Failed to create memo entry.", status="fail")


@memo_bp.post("/api/suggest", name="memo.api_suggest")
async def api_suggest_memo(request: Request):
    """
    AI回答からおすすめのタイトルを提案するエンドポイント
    Endpoint to suggest an appropriate title from AI response text.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request object.

    Returns:
        Response: 提案されたタイトル候補一覧を含むJSONレスポンス / JSON response containing suggestions.
    """
    # ユーザー認証の確認。未ログインなら401を返却
    # Verify user authentication. Return 401 Unauthorized if not logged in.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式のリクエストデータ取得を強制
    # Require JSON request dictionary.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # リクエストボディのフォーマット検証
    # Validate request payload schema.
    payload, validation_error = validate_payload_model(
        data,
        MemoSuggestRequest,
        error_message="AIの回答を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # LLM等を用いて最適なタイトル候補を提案
        # Suggest appropriate title options using the system logic.
        result = await run_blocking(
            _memo_attr("suggest_title"),
            payload.ai_response,
        )
        return jsonify({"status": "success", **result})
    except Exception:
        # 提案処理失敗時のエラーハンドリング
        # Handle exceptions in title suggestion.
        return log_and_internal_server_error(logger, "Memo suggestion failed.", status="fail")


@memo_bp.post("/api/bulk", name="memo.api_bulk")
async def api_bulk_memo(request: Request):
    """
    複数メモに対して一括操作を行うエンドポイント
    Endpoint to perform bulk operations on multiple memos.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 一括操作の実行結果を含むJSONレスポンス / JSON response of execution results.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式のリクエストデータ取得を強制
    # Require JSON format payload.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # バリデーション実行
    # Validate bulk parameters.
    payload, validation_error = validate_payload_model(
        data,
        MemoBulkActionRequest,
        error_message="一括操作のパラメータが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # 指定された一括アクション（削除、ピン留め、アーカイブ、コレクション設定など）を実行
        # Execute the bulk action (delete, pin, archive, set collection) on given memo IDs.
        result = await run_blocking(
            _memo_attr("_bulk_action"),
            user_id,
            payload.action,
            payload.memo_ids,
            collection_id=payload.collection_id,
        )
        return jsonify({"status": "success", **result})
    except Error:
        # 一括処理DBエラー時のハンドリング
        # Return internal server error if bulk DB query fails.
        return log_and_internal_server_error(logger, "Bulk memo action failed.", status="fail")


@memo_bp.post("/api/reorder", name="memo.api_reorder")
async def api_reorder_memo(request: Request):
    """
    メモの並び順（ドラッグ＆ドロップ順）を更新するエンドポイント
    Endpoint to update manual sort sequence of a memo (drag and drop).

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 更新されたメモ情報を含むJSONレスポンス / JSON response containing updated memo details.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式の要求を検証
    # Require JSON request data.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # 並び替えパラメータの検証
    # Validate payload parameters.
    payload, validation_error = validate_payload_model(
        data,
        MemoReorderRequest,
        error_message="並べ替えのパラメータが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # メモのソート順序位置を更新
        # Update the position of the target memo relative to target neighbors.
        memo = await run_blocking(
            _memo_attr("_reorder_memo"),
            user_id,
            payload.memo_id,
            before_id=payload.before_id,
            after_id=payload.after_id,
        )
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        # メモが見つからないなど、バリデーションエラーの場合は例外ハンドラに応じたレスポンスを返す
        # Handle business logic exceptions and return appropriate error payload.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DB書き込み失敗時のエラーハンドリング
        # Handle database connection or SQL exception.
        return log_and_internal_server_error(logger, "Failed to reorder memo entry.", status="fail")


@memo_bp.get("/api/export", name="memo.api_export")
async def api_export_memos(
    request: Request,
    format: str = "markdown",
    ids: str = "",
):
    """
    メモデータをエクスポート形式 (Markdown, JSON, CSV) でダウンロードするエンドポイント
    Endpoint to export and stream memos as files in Markdown, JSON, or CSV formats.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        format (str): エクスポートするファイル形式 / Output file format ("markdown", "json", "csv").
        ids (str): 対象メモIDのカンマ区切り文字列 / Comma-separated list of memo IDs to filter.

    Returns:
        StreamingResponse: ファイルストリームレスポンス / StreamingResponse representing file attachment.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    memo_ids: list[int] | None = None
    # 特定のメモID一覧がカンマ区切りで渡された場合、パースする
    # Parse list of specific memo IDs if passed as comma-separated string.
    if ids.strip():
        try:
            memo_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
        except ValueError:
            return jsonify({"status": "fail", "error": "IDの形式が不正です。"}, status_code=400)

    # サポートされている形式かどうか確認
    # Validate target export format.
    valid_formats = {"markdown", "json", "csv"}
    if format not in valid_formats:
        format = "markdown"

    try:
        # 指定されたメモデータをDBから取得
        # Retrieve target memos for export.
        memos = await run_blocking(_memo_attr("_fetch_memos_for_export"), user_id, memo_ids)

        # フォーマットに応じたファイルデータおよびContent-Typeの設定
        # Format mapping and headers config for file streaming.
        if format == "json":
            content = _memo_attr("_build_json_export")(memos)
            media_type = "application/json"
            filename = "memos.json"
        elif format == "csv":
            content = _memo_attr("_build_csv_export")(memos)
            media_type = "text/csv; charset=utf-8"
            filename = "memos.csv"
        else:
            content = _memo_attr("_build_markdown_export")(memos)
            media_type = "text/markdown; charset=utf-8"
            filename = "memos.md"

        # ストリーミングレスポンスとしてクライアントに返却（文字エンコーディングはUTF-8）
        # Return StreamingResponse with matching content disposition and UTF-8 encoding.
        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    except Error:
        # エクスポート失敗時のエラーハンドリング
        # Handle exceptions in formatting or fetching memos.
        return log_and_internal_server_error(logger, "Export failed.", status="fail")


@memo_bp.get("/api/collections", name="memo.api_collections_list")
async def api_list_collections(request: Request):
    """
    所有するコレクションの一覧を取得するエンドポイント
    Endpoint to retrieve list of user's memo collections.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: コレクション一覧を含むJSONレスポンス / JSON response listing all collections.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # DBからコレクション一覧を取得
        # Query collections from the database.
        collections = await run_blocking(_memo_attr("_fetch_collections"), user_id)
        return jsonify({"status": "success", "collections": collections})
    except Error:
        # コレクション取得失敗時のエラーハンドリング
        # Handle SQL errors during collection retrieval.
        return log_and_internal_server_error(logger, "Failed to load collections.", status="fail")


@memo_bp.post("/api/collections", name="memo.api_collections_create")
async def api_create_collection(request: Request):
    """
    新しいコレクションを作成するエンドポイント
    Endpoint to create a new memo collection.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 作成されたコレクション情報を含むJSONレスポンス / JSON response with created collection info.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式の要求を検証
    # Require JSON request dictionary.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # コレクション作成用のパラメータバリデーション
    # Validate payload for collection creation.
    payload, validation_error = validate_payload_model(
        data,
        MemoCollectionCreateRequest,
        error_message="コレクション名を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # DBに新しいコレクションを追加
        # Insert a new collection record in the DB.
        collection = await run_blocking(
            _memo_attr("_insert_collection"), user_id, payload.name, payload.color
        )
        return jsonify({"status": "success", "collection": collection})
    except Error as exc:
        # ユニークキー制約違反（同名コレクション）の場合は409衝突を返す
        # Return 409 Conflict if unique constraint violated (duplicate collection name).
        if getattr(exc, "pgcode", None) == "23505":
            return jsonify(
                {"status": "fail", "error": "同名のコレクションが既に存在します。"},
                status_code=409,
            )
        # その他DB書き込みエラー
        # Handle general database insert exception.
        return log_and_internal_server_error(logger, "Failed to create collection.", status="fail")


@memo_bp.patch("/api/collections/{collection_id:int}", name="memo.api_collections_update")
async def api_update_collection(request: Request, collection_id: int):
    """
    コレクション情報を更新するエンドポイント
    Endpoint to update an existing memo collection.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        collection_id (int): 更新対象のコレクションID / Target collection ID to update.

    Returns:
        Response: 更新されたコレクション詳細情報を含むJSONレスポンス / JSON response with updated collection details.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式の要求を検証
    # Require JSON request data.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # コレクション更新のパラメータを検証
    # Validate update payload schema.
    payload, validation_error = validate_payload_model(
        data,
        MemoCollectionUpdateRequest,
        error_message="更新データが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # DBのコレクション情報を更新
        # Update details of the specified collection in DB.
        collection = await run_blocking(
            _memo_attr("_update_collection"), user_id, collection_id, payload.name, payload.color
        )
        return jsonify({"status": "success", "collection": collection})
    except ApiServiceError as exc:
        # コレクションが見つからないなどのサービスエラーを返却
        # Return specific service error if collection is missing or not owned.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # SQL実行例外などのエラーハンドリング
        # Return 500 status on database update failure.
        return log_and_internal_server_error(logger, "Failed to update collection.", status="fail")


@memo_bp.delete("/api/collections/{collection_id:int}", name="memo.api_collections_delete")
async def api_delete_collection(request: Request, collection_id: int):
    """
    コレクションを削除するエンドポイント
    Endpoint to delete a memo collection.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        collection_id (int): 削除対象のコレクションID / Target collection ID to delete.

    Returns:
        Response: 処理結果を示すJSONレスポンス / Success status JSON.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # 指定されたコレクションをDBから削除（所属していたメモの関連付けは解除される）
        # Delete the collection from database (memos belonging to it will have association cleared).
        await run_blocking(_memo_attr("_delete_collection"), user_id, collection_id)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        # 所有権違反などのサービスエラーを返却
        # Handle authorization or existence service checks.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # データベース削除処理エラー時のハンドリング
        # Return 500 on database failure.
        return log_and_internal_server_error(logger, "Failed to delete collection.", status="fail")


@memo_bp.post("/api/share", name="memo.api_share")
async def api_share_memo(request: Request):
    """
    メモの共有状態を作成または取得するエンドポイント
    Endpoint to generate or get a share token/link for a memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 共有メタデータを含むJSONレスポンス / JSON response containing share metadata.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式の要求を検証
    # Require JSON request format.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # リクエストデータ（対象メモID）の検証
    # Validate payload to find target memo ID.
    payload, validation_error = validate_payload_model(
        data, ShareMemoRequest, error_message="共有するメモを指定してください。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    # 共有設定（強制リフレッシュフラグや有効日数）の検証
    # Validate link settings (expiration, forced refresh).
    share_options, options_error = validate_payload_model(
        data, MemoShareCreateRequest, error_message="共有リンク設定が不正です。", status="fail",
    )
    if options_error is not None:
        return options_error

    try:
        # トークンを生成または取得
        # Create or fetch shared memo token.
        share_state = await run_blocking(
            _memo_attr("create_or_get_shared_memo_token"),
            payload.memo_id,
            user_id,
            force_refresh=share_options.force_refresh,
            expires_in_days=share_options.expires_in_days,
        )
        # ペイロードをシリアライズして返却
        # Serialize the share metadata and return success.
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        # メモが見つからない、または所有権が無い場合のエラーハンドリング
        # Return service error if memo does not exist or isn't owned.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DBトークン作成時のエラーハンドリング
        # Handle general SQL error.
        return log_and_internal_server_error(logger, "Failed to create share link for memo entry.", status="fail")


@memo_bp.get("/api/shared", name="memo.api_shared")
async def api_shared_memo(request: Request):
    """
    共有トークンを用いて共有されたメモを一般公開用に取得するエンドポイント
    Public endpoint to retrieve a shared memo using its token.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 共有されたメモの詳細情報を含むJSONレスポンス / JSON response with shared memo details.
    """
    # クエリパラメータから共有トークンを取得
    # Get share token from query parameters.
    token = request.query_params.get("token", "").strip()
    if not token:
        return jsonify({"error": ERROR_TOKEN_REQUIRED}, status_code=400)

    try:
        # トークンによる検証とデータ取得を実行
        # Verify token validity and load shared memo details.
        payload_result = await run_blocking(_memo_attr("get_shared_memo_payload"), token)
        # タプル形式 (payload, status_code) で返ってきた場合は対応するステータスコードで返す
        # If payload and status code tuple returned, respond with status.
        if isinstance(payload_result, tuple) and len(payload_result) == 2:
            payload, status_code = payload_result
            return jsonify(payload, status_code=status_code)
        return jsonify(payload_result)
    except ApiServiceError as exc:
        # トークン無効化、期限切れなどのエラーを返却
        # Return service error on expired/revoked/invalid tokens.
        return jsonify_service_error(exc)
    except Error:
        # 読み込み処理失敗時のエラーハンドリング
        # Respond with 500 status on database load failure.
        return log_and_internal_server_error(logger, "Failed to load shared memo payload.")


@memo_bp.get("/api/{memo_id:int}", name="memo.api_detail")
async def api_memo_detail(request: Request, memo_id: int):
    """
    メモ詳細情報を取得するエンドポイント
    Endpoint to retrieve detailed info for a single memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: メモ詳細情報を含むJSONレスポンス / JSON response with memo details.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # DBから指定メモの詳細データを取得
        # Retrieve memo detail data from DB.
        memo = await run_blocking(_memo_attr("_fetch_memo_detail"), user_id, memo_id)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        # 所有権や存在確認のエラーハンドリング
        # Return service error if not authorized or not found.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DBエラー時のハンドリング
        # Respond with 500 status on database connection issue.
        return log_and_internal_server_error(logger, "Failed to load memo detail.", status="fail")


@memo_bp.patch("/api/{memo_id:int}", name="memo.api_update")
async def api_update_memo(request: Request, memo_id: int):
    """
    メモ情報（タイトル、コンテンツ、コレクション等）を更新するエンドポイント
    Endpoint to update details of a memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): 対象メモID / Target memo ID to update.

    Returns:
        Response: 更新されたメモ詳細情報を含むJSONレスポンス / JSON response with updated memo.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式の要求を検証
    # Require JSON request payload.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # メモ更新用のパラメータ検証
    # Validate memo update request schema.
    payload, validation_error = validate_payload_model(
        data, MemoUpdateRequest, error_message="更新データが不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    # 更新されるプロパティがどれもない場合はエラーを返す
    # Verify that at least one field is provided for update.
    if (
        payload.title is None
        and payload.ai_response is None
        and payload.collection_id is None
        and not payload.clear_collection
        and payload.background_color is None
        and not payload.clear_background_color
    ):
        return jsonify({"status": "fail", "error": "更新する項目を指定してください。"}, status_code=400)

    try:
        # データベース内のメモを更新
        # Commit memo edits to DB.
        memo = await run_blocking(
            _memo_attr("_update_memo"),
            user_id,
            memo_id,
            title=payload.title,
            ai_response=payload.ai_response,
            collection_id=payload.collection_id,
            clear_collection=payload.clear_collection,
            background_color=payload.background_color,
            clear_background_color=payload.clear_background_color,
        )
        # コンテンツまたはタイトルが更新された場合、埋め込みベクトルを再スケジュール
        # If content or title changed, schedule updating the semantic search embedding.
        if payload.ai_response is not None or payload.title is not None:
            _memo_attr("_schedule_embedding")(
                memo_id,
                memo.get("title", ""),
                memo.get("ai_response", ""),
                memo.get("revision"),
            )
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        # 所有権違反などのエラーを返却
        # Return service error if edit not permitted.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DB処理エラー
        # Respond with 500 status on database write failure.
        return log_and_internal_server_error(logger, "Failed to update memo entry.", status="fail")


@memo_bp.delete("/api/{memo_id:int}", name="memo.api_delete")
async def api_delete_memo(request: Request, memo_id: int):
    """
    メモを削除するエンドポイント
    Endpoint to delete a memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): 削除対象のメモID / Target memo ID to delete.

    Returns:
        Response: 処理結果を示すJSONレスポンス / Success status JSON.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # DBからメモを物理/論理削除
        # Delete the memo record from database.
        await run_blocking(_memo_attr("_delete_memo"), user_id, memo_id)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        # 所有権違反などのエラーを返却
        # Return service error if delete not authorized.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DB処理エラー
        # Respond with 500 status on database deletion failure.
        return log_and_internal_server_error(logger, "Failed to delete memo entry.", status="fail")


@memo_bp.post("/api/{memo_id:int}/archive", name="memo.api_archive")
async def api_archive_memo(request: Request, memo_id: int):
    """
    メモのアーカイブ状態を切り替えるエンドポイント
    Endpoint to set or toggle a memo's archived state.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: 更新されたメモ情報を含むJSONレスポンス / JSON response with updated memo.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # リクエストデータ取得
    # Retrieve request content.
    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    # アーカイブ切り替え用のトグル設定を検証
    # Validate the archive payload setting.
    payload, validation_error = validate_payload_model(
        data, MemoToggleRequest, error_message="アーカイブ設定が不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # アーカイブ状態を設定・更新
        # Update the archive state in the DB.
        memo = await run_blocking(_memo_attr("_set_memo_archive_state"), user_id, memo_id, payload.enabled)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        # 所有権違反などのエラーを返却
        # Return service error if not authorized.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DB処理エラー
        # Respond with 500 status on database write failure.
        return log_and_internal_server_error(logger, "Failed to archive memo entry.", status="fail")


@memo_bp.post("/api/{memo_id:int}/pin", name="memo.api_pin")
async def api_pin_memo(request: Request, memo_id: int):
    """
    メモのピン留め状態を切り替えるエンドポイント
    Endpoint to set or toggle a memo's pinned state.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: 更新されたメモ情報を含むJSONレスポンス / JSON response with updated memo.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # リクエストデータ取得
    # Retrieve request body.
    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    # ピン留め用トグル設定の検証
    # Validate the toggle setting schema.
    payload, validation_error = validate_payload_model(
        data, MemoToggleRequest, error_message="ピン留め設定が不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # ピン留め状態を設定・更新
        # Update the pinned state in the DB.
        memo = await run_blocking(_memo_attr("_set_memo_pin_state"), user_id, memo_id, payload.enabled)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        # 所有権違反などのサービスエラーを返却
        # Return service error if not authorized.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DB処理エラー
        # Respond with 500 status on database write failure.
        return log_and_internal_server_error(logger, "Failed to pin memo entry.", status="fail")


@memo_bp.get("/api/{memo_id:int}/share", name="memo.api_share_detail")
async def api_memo_share_detail(request: Request, memo_id: int):
    """
    メモの共有メタデータ詳細を取得するエンドポイント
    Endpoint to get share details for a specific memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: 共有メタデータを含むJSONレスポンス / JSON response containing share status.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # 共有状態をDBから取得
        # Retrieve share status from the database.
        share_state = await run_blocking(_memo_attr("get_memo_share_state"), memo_id, user_id)
        # ペイロードをシリアライズして返却
        # Serialize share metadata.
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        # 所有権違反や対象メモ無しのサービスエラー
        # Return service error if not authorized.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DB処理エラー
        # Respond with 500 status on database query failure.
        return log_and_internal_server_error(logger, "Failed to load memo share status.", status="fail")


@memo_bp.post("/api/{memo_id:int}/share", name="memo.api_share_refresh")
async def api_memo_share_refresh(request: Request, memo_id: int):
    """
    メモの共有トークンをリフレッシュするエンドポイント
    Endpoint to refresh or recreate a memo's share token/expiration.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: 新しい共有メタデータを含むJSONレスポンス / JSON response with refreshed share details.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # リクエストデータ取得
    # Retrieve request body.
    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    # 共有トークン設定のパラメータ検証
    # Validate the share creation options schema.
    payload, validation_error = validate_payload_model(
        data, MemoShareCreateRequest, error_message="共有リンク設定が不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # トークンを再生成、または既存のものを取得して設定更新
        # Refresh or recreate the share token.
        share_state = await run_blocking(
            _memo_attr("create_or_get_shared_memo_token"),
            memo_id,
            user_id,
            force_refresh=payload.force_refresh,
            expires_in_days=payload.expires_in_days,
        )
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        # 所有権や対象メモが見つからないエラー
        # Return service error if not authorized.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DB更新エラー
        # Respond with 500 status on database write failure.
        return log_and_internal_server_error(logger, "Failed to refresh memo share status.", status="fail")


@memo_bp.post("/api/{memo_id:int}/share/revoke", name="memo.api_share_revoke")
async def api_memo_share_revoke(request: Request, memo_id: int):
    """
    メモの共有設定を無効化（トークン失効）するエンドポイント
    Endpoint to revoke the share token for a specific memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: 更新された共有メタデータを含むJSONレスポンス / JSON response containing revoked share status.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # 共有トークンを無効化（無効化日時を更新）
        # Revoke the sharing token for the memo.
        share_state = await run_blocking(_memo_attr("revoke_shared_memo_token"), memo_id, user_id)
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        # 所有権や存在確認のエラー
        # Return service error if not authorized.
        return jsonify_service_error(exc, status="fail")
    except Error:
        # DB更新エラー
        # Respond with 500 status on database write failure.
        return log_and_internal_server_error(logger, "Failed to revoke memo share link.", status="fail")


@memo_bp.api_route("", methods=["GET", "POST"], name="memo.create_memo")
async def create_memo(request: Request):
    """
    フロントエンドへのリダイレクト用デフォルトエントリーポイント
    Fallback/default route to redirect memo queries directly to the frontend app.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request object.

    Returns:
        Response: リダイレクトレスポンス / Redirect response.
    """
    # GETリクエストなら302、POSTリクエストなら303でリダイレクト
    # Redirect with 302 for GET or 303 for POST.
    status_code = 302 if request.method == "GET" else 303
    return redirect_to_frontend(request, status_code=status_code)
