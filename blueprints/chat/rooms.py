import base64
import binascii
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import Depends, Request

from services.auth_limits import (
    AuthLimitService,
    consume_guest_chat_daily_limit,
    get_seconds_until_tomorrow,
    get_auth_limit_service,
)
from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.chat_service import (
    create_or_get_shared_chat_token,
    create_chat_room_in_db,
    delete_chat_room_for_user,
    delete_chat_rooms_for_user,
    fork_shared_chat_into_db_room,
    get_shared_chat_room_payload,
    list_chat_rooms,
    rename_chat_room_in_db,
    validate_room_owner,
)
from services.project_service import assign_room_to_project
from services.share_common import build_public_share_url

from services.request_models import (
    ChatRoomIdRequest,
    ChatRoomIdsRequest,
    ForkSharedChatRoomRequest,
    NewChatRoomRequest,
    RenameChatRoomRequest,
    ShareChatRoomRequest,
)
from services.web import (
    jsonify,
    jsonify_rate_limited,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)
from services.error_messages import (
    ERROR_CHAT_ROOM_NOT_FOUND,
    ERROR_LOGIN_REQUIRED,
    ERROR_TOKEN_REQUIRED,
)

from . import (
    chat_bp,
    cleanup_ephemeral_chats,
    ephemeral_store,
    get_session_id,
    get_temporary_user_store_key,
    register_guest_room,
    unregister_guest_room,
)

logger = logging.getLogger(__name__)

MAX_FORKED_MESSAGES = 500


async def _fork_shared_chat_into_ephemeral_room(
    token: str,
    sid: str,
    room_id: str,
) -> dict[str, Any]:
    """Load the shared room asynchronously, then write only to the ephemeral store."""
    payload = await get_shared_chat_room_payload(token)
    room = payload.get("room") if isinstance(payload, dict) else None
    title = str((room or {}).get("title") or "共有チャット").strip() or "共有チャット"
    messages = [
        message
        for message in (payload.get("messages") if isinstance(payload, dict) else [])
        if isinstance(message, dict)
    ][:MAX_FORKED_MESSAGES]
    await run_blocking(ephemeral_store.create_room, sid, room_id, title)
    copied = 0
    for message in messages:
        role = "user" if message.get("sender") == "user" else "assistant"
        message_parts = message.get("message_parts")
        appended = await run_blocking(
            ephemeral_store.append_message,
            sid,
            room_id,
            role,
            str(message.get("message") or ""),
            message_parts=message_parts if isinstance(message_parts, list) else None,
        )
        if not appended:
            break
        copied += 1
    return {"id": room_id, "title": title, "mode": "temporary", "message_count": copied}

# チャットルーム一覧のデフォルトの1ページ表示件数
# Default page size for chat room lists.
CHAT_ROOMS_DEFAULT_PAGE_SIZE = 20

# チャットルーム一覧の最大許容表示件数
# Maximum allowed page size for chat room lists to prevent over-fetching.
CHAT_ROOMS_MAX_PAGE_SIZE = 100


# リクエストから認証制限サービスを解決するヘルパー関数
# Helper function to resolve the AuthLimitService instance from the request.
def _resolve_auth_limit_service(
    request: Request,
    service: AuthLimitService | None,
) -> AuthLimitService:
    """
    引数で渡された制限サービス、あるいはRequestインスタンスからAuthLimitServiceのインスタンスを解決します。
    Resolves the AuthLimitService instance from the provided parameter or Request.
    """
    if isinstance(service, AuthLimitService):
        return service
    return get_auth_limit_service(request)


# クエリ値から正の整数をパースし、デフォルト値の設定および上限クランプを行う関数
# Parse positive integer from string value, applying defaults and clamping to a maximum limit.
def _parse_positive_int(value: str | None, default: int, maximum: int) -> int:
    """
    クエリパラメータなどの文字列値を解析して正の整数に変換し、上限値と下限値の範囲内に収めます。
    Parses a string value into a positive integer, clamping it between 1 and a specified maximum.
    """
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        # 変換に失敗した場合はデフォルト値を返却
        # Return default value on parsing failure
        return default
    # 最小値1、最大値maximumで範囲をクランプ
    # Clamp the parsed value between 1 and maximum
    return min(max(1, parsed), maximum)


# リクエストからルーム一覧取得用のページング情報（リミット、カーソル）を解析する関数
# Parse paging parameters (limit and cursor) from request query parameters.
def _resolve_room_list_pagination(request: Request) -> tuple[int, tuple[datetime, str] | None]:
    """
    HTTP GETリクエストのクエリパラメータからlimitおよびcursorパラメータを取り出し、パースします。
    Extracts and parses the limit and cursor values from HTTP GET query parameters.
    """
    # 1ページあたり取得数の決定
    # Determine the fetch limit
    limit = _parse_positive_int(
        request.query_params.get("limit"),
        CHAT_ROOMS_DEFAULT_PAGE_SIZE,
        CHAT_ROOMS_MAX_PAGE_SIZE,
    )
    # カーソルのデコード処理
    # Decode the cursor
    cursor = _decode_room_list_cursor(request.query_params.get("cursor"))
    return limit, cursor


# ページネーションカーソル文字列（Base64 URL Safe）をデコードし日時とルームIDを取り出す関数
# Decode a URL-safe Base64 cursor string into a tuple of (last activity datetime, room_id) for pagination.
def _decode_room_list_cursor(value: str | None) -> tuple[datetime, str] | None:
    """
    Base64エンコードされたURLセーフなカーソル文字列をデコードし、
    そこに含まれる最終アクティビティ日時(datetime)とルームID(str)をタプルで返します。
    Decodes a Base64 URL-safe cursor string and returns a tuple of (last activity datetime, room_id).
    """
    if not value:
        return None
    try:
        # Base64デコード用にパディングを補正
        # Add padding back if necessary
        padded = value + "=" * (-len(value) % 4)
        # asciiエンコードしてデコード
        # Decode the URL-safe Base64 encoded ascii string to utf-8 bytes
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
        
        last_activity_at = payload.get("last_activity_at") or payload.get("created_at")
        room_id = payload.get("id")
        if not isinstance(last_activity_at, str) or not isinstance(room_id, str) or not room_id:
            raise ValueError
            
        # Z（UTC）をタイムゾーンオフセット形式に正規化してdatetimeオブジェクトを生成
        # Normalize Z with UTC offset formatting and parse to datetime
        normalized_last_activity_at = last_activity_at.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized_last_activity_at), room_id
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        # 不正なカーソルの場合はエラーをスロー
        # Raise ApiServiceError on malformed cursor strings
        raise ApiServiceError("invalid cursor", 400)


# ルームデータからページネーションカーソル用のBase64 URL Safe文字列を作成する関数
# Encode room metadata (last_activity_at and id) into a URL-safe Base64 cursor string for pagination.
def _encode_room_list_cursor(room: dict[str, Any]) -> str | None:
    """
    ルーム情報（最終アクティビティ日時およびルームID）をJSON化し、URLセーフなBase64文字列にエンコードして次のページ取得用カーソルを生成します。
    Serializes room metadata (last_activity_at and id) and encodes it to a URL-safe Base64 string cursor.
    """
    last_activity_at = room.get("last_activity_at")
    room_id = room.get("id")
    if not isinstance(last_activity_at, str) or not isinstance(room_id, str) or not room_id:
        return None
    
    # 辞書をコンパクトなJSON文字列にする
    # Convert dict to a compact JSON string
    payload = json.dumps(
        {"last_activity_at": last_activity_at, "id": room_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Base64エンコードし、末尾のパディング(=)を除去してURLセーフに変換
    # Base64 encode and strip trailing padding (=) for URL compatibility
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


# データベースに保存されているユーザーのチャットルーム一覧を取得する関数（カーソルページング対応）
# Fetch persisted chat rooms for a user from the database using cursor-based pagination.
async def _fetch_persisted_user_rooms(
    user_id: int,
    *,
    limit: int | None = None,
    cursor: tuple[datetime, str] | None = None,
) -> list[dict[str, Any]]:
    """
    DBに永続化されているユーザーのチャットルーム情報を、作成日時の降順・IDの降順で取得します（一時的なルームは除外）。
    Retrieves the user's persistent chat rooms from the database, sorted newest first.
    """
    return await list_chat_rooms(user_id, limit=limit, cursor=cursor)


# 指定ルームのモード（通常モードnormalまたは一時モードtemporary）を判定する関数
# Resolve whether the room is normal (persisted in DB) or temporary (ephemeral store) for authenticated requests.
async def _resolve_authenticated_room_mode(
    user_id: int,
    room_id: str,
    forbidden_message: str,
) -> tuple[str | None, Any]:
    """
    ユーザーIDとルームIDから、対象ルームが「一時ルーム(temporary)」か「DBに永続化されたルーム(normal/その他)」かを判定し、
    所有権の検証も同時に行います。
    Determines whether a chat room is temporary or persisted, validating its ownership.
    """
    temporary_sid = get_temporary_user_store_key(user_id)
    # エフェメラルストアにルームがある場合はtemporaryと判断
    # If room exists in ephemeral store, treat it as temporary
    if await run_blocking(ephemeral_store.room_exists, temporary_sid, room_id):
        return "temporary", None

    # DB内のルームの場合、所有者が正しいか検証
    # If room is in DB, validate that the current user owns it
    owner_result = await validate_room_owner(room_id, user_id, forbidden_message)
    legacy_response = _legacy_error_response(owner_result)
    if legacy_response is not None:
        # 所有権のないエラーレスポンスがある場合は返却
        # Return error response if validation fails
        return None, legacy_response
    return str(owner_result or "normal"), None


# DBから指定されたチャットルームとそのメッセージ履歴を削除する関数
# Delete a specific chat room and its message history from the database after verifying ownership.
async def _delete_room_for_user(room_id: str, user_id: int) -> dict[str, str]:
    """
    DBから該当するチャットルーム、およびそのチャット履歴を一連のトランザクションとして削除します。
    Deletes the chat room and its history from the database in a single transaction.
    """
    return await delete_chat_room_for_user(room_id, user_id)


# ルームIDリストから重複したIDを取り除く関数
# Deduplicate a list of room ID strings.
def _unique_room_ids(room_ids: list[str]) -> list[str]:
    """
    リスト内の重複したチャットルームIDを取り除いたユニークなリストを返します。
    Returns a deduplicated list of chat room IDs.
    """
    return list(dict.fromkeys(room_ids))


# SQLクエリの IN 句用のプレースホルダ（%s）を組み立てる関数
# Generate SQL placeholder parameter markers (e.g., "%s, %s") for an IN clause.
def _placeholders(count: int) -> str:
    """
    SQLのIN句用のパラメータプレースホルダ文字列をカンマ区切りで生成します。
    Generates comma-separated "%s" placeholders for SQL IN clauses.
    """
    return ", ".join(["%s"] * count)


# 複数のチャットルームとそのメッセージ履歴を一括削除する関数
# Bulk delete multiple chat rooms and their history from the database after verifying ownership.
async def _delete_rooms_for_user(room_ids: list[str], user_id: int) -> dict[str, Any]:
    """
    複数のルームIDについて、すべての所有権を検証した上で、一括で履歴とルームデータを削除します。
    Atomically deletes multiple chat rooms and histories after verifying ownership of all target rooms.
    """
    return await delete_chat_rooms_for_user(room_ids, user_id)


# レガシーなエラーレスポンス形式を FastAPI 互換の JSONResponse に整形するヘルパー関数
# Format a legacy error response payload into a FastAPI-compatible response.
def _legacy_error_response(result: Any):
    """
    検証サービスが返したタプル (payload, status_code) 形式のエラーオブジェクトを、FastAPIのJSONResponseに整形します。
    Formats a legacy error tuple (payload, status_code) into a FastAPI JSON response.
    """
    if not (isinstance(result, tuple) and len(result) == 2):
        return None
    payload, status_code = result
    if payload is None:
        return None
    if isinstance(payload, dict) and isinstance(status_code, int):
        return jsonify(payload, status_code=status_code)
    return None


# 新しいチャットルーム（通常または一時ルーム）を作成するAPIエンドポイント
# API endpoint to create a new chat room (normal/persisted or temporary/ephemeral).
@chat_bp.post("/api/new_chat_room", name="chat.new_chat_room")
async def new_chat_room(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
):
    """
    新しいチャットルームを作成します。ログインユーザーの場合はDBに永続化、非ログインユーザーの場合はエフェメラルストアへ保存します。
    Creates a new chat room. Either persists to DB (for authenticated users) or registers in ephemeral store (for guests).
    """
    # 制限サービスを解決
    # Resolve the AuthLimitService instance
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    
    # 期限切れのエフェメラルチャットルームを自動クリーンアップ
    # Automatically clean up expired guest/temporary rooms
    await run_blocking(cleanup_ephemeral_chats)
    
    # リクエストデータが辞書型であることを要求
    # Verify request body is a JSON dictionary
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # 新規作成パラメータのスキーマバリデーション
    # Validate payload parameters using the Pydantic schema
    payload, validation_error = validate_payload_model(
        data,
        NewChatRoomRequest,
        error_message="'id' フィールドが必要です。",
    )
    if validation_error is not None:
        return validation_error

    room_id = payload.id
    title = payload.title
    mode = payload.mode
    project_id = payload.project_id

    session = request.session
    if "user_id" in session:
        # ログインユーザー：
        # ログインユーザーは通常ルームだけ DB 永続化し、temporary は一時ストアだけで扱う
        # Persist only normal rooms for authenticated users; keep temporary rooms ephemeral.
        user_id = session["user_id"]
        try:
            if mode == "temporary":
                temporary_sid = get_temporary_user_store_key(user_id)
                await run_blocking(ephemeral_store.create_room, temporary_sid, room_id, title)
            else:
                await create_chat_room_in_db(room_id, user_id, title, mode)
                # プロジェクト指定時はルームを紐づける（通常ルームのみ）。失敗してもルーム作成は成功扱い。
                # Assign the room to the project when requested (normal rooms only).
                if project_id is not None:
                    try:
                        await assign_room_to_project(room_id, user_id, project_id)
                    except Exception:
                        logger.warning("Failed to assign new room to project %s.", project_id)
            return jsonify(
                {
                    "message": "チャットルームが作成されました。",
                    "id": room_id,
                    "title": title,
                    "mode": mode,
                },
                status_code=201,
            )
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to create chat room for authenticated user.",
            )
    else:
        # 非ログインユーザー（ゲスト）：
        # 非ログインユーザーはサーバー側の日次カウンタで回数制限する
        # Enforce guest daily quota with a server-side counter.
        allowed, message = await run_blocking(
            consume_guest_chat_daily_limit,
            request,
            service=resolved_auth_limit_service,
        )
        if not allowed:
            # 制限に達した場合はエラー
            # Return rate limit error response when limit exceeded
            return jsonify_rate_limited(
                message or "1日10回までです",
                retry_after=get_seconds_until_tomorrow(),
            )

        sid = get_session_id(session)
        # エフェメラルストアにゲストルームを作成
        # Save chat room in ephemeral guest store
        await run_blocking(ephemeral_store.create_room, sid, room_id, title)
        # セッションにゲストルームIDを登録
        # Register guest room ID in the session
        register_guest_room(session, room_id)

        return jsonify(
            {
                "message": "エフェメラルチャットルームが作成されました。",
                "id": room_id,
                "title": title,
                "mode": "temporary",
            },
            status_code=201,
        )


# ユーザーのチャットルーム一覧を取得するAPIエンドポイント
# API endpoint to fetch a paginated list of chat rooms for the authenticated user.
@chat_bp.get("/api/get_chat_rooms", name="chat.get_chat_rooms")
async def get_chat_rooms(request: Request):
    """
    現在のユーザーに関連づけられたチャットルーム一覧を取得します（ログインユーザーのみDBからページネーション取得）。
    Retrieves the list of chat rooms for the current user. Authenticated users read paginated lists from DB.
    """
    # エフェメラルチャットの自動クリーンアップ
    # Automatically clean up expired ephemeral rooms
    await run_blocking(cleanup_ephemeral_chats)
    session = request.session
    if "user_id" in session:
        # ログインユーザー：DBから取得
        # Authenticated users read room list from DB.
        user_id = session["user_id"]
        try:
            # limit, cursorの取得
            # Extract and parse pagination keys
            limit, cursor = _resolve_room_list_pagination(request)
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
            
        # has_moreを判定するため、limitより1件多く取得を試みる
        # Fetch 1 extra item to check if there are subsequent pages
        fetch_limit = limit + 1
        try:
            persisted_rooms = await _fetch_persisted_user_rooms(
                user_id,
                limit=fetch_limit,
                cursor=cursor,
            )
            has_more = len(persisted_rooms) > limit
            # 結果をクランプ
            # Trim results to the requested limit
            persisted_rooms = persisted_rooms[:limit]
            # 次のページ用のカーソル文字列をエンコード
            # Encode next cursor string if there are more rooms
            next_cursor = _encode_room_list_cursor(persisted_rooms[-1]) if has_more and persisted_rooms else None
            return jsonify(
                {
                    "rooms": persisted_rooms,
                    "pagination": {
                        "limit": limit,
                        "has_more": has_more,
                        "next_cursor": next_cursor,
                    },
                }
            )
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to fetch chat rooms for authenticated user.",
            )
    else:
        # 非ログインユーザーにはサイドバー上でチャットルーム一覧は表示しない
        # Do not show sidebar room list for guests.
        return jsonify(
            {
                "rooms": [],
                "pagination": {
                    "limit": CHAT_ROOMS_DEFAULT_PAGE_SIZE,
                    "has_more": False,
                    "next_cursor": None,
                },
            }
        )


# チャットルームを削除するAPIエンドポイント
# API endpoint to delete a specific chat room and its contents.
@chat_bp.post("/api/delete_chat_room", name="chat.delete_chat_room")
async def delete_chat_room(request: Request):
    """
    指定されたチャットルームを削除します。ルームがDBにあるか一時ストアにあるかに応じて適切に削除処理を切り替えます。
    Deletes the specified chat room from either database or ephemeral store depending on its mode.
    """
    await run_blocking(cleanup_ephemeral_chats)
    
    # リクエストデータ取得
    # Extract request payload
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # スキーマ検証
    # Validate payload keys
    payload, validation_error = validate_payload_model(
        data,
        ChatRoomIdRequest,
        error_message="room_id is required",
    )
    if validation_error is not None:
        return validation_error

    room_id = payload.room_id
    session = request.session
    
    if "user_id" in session:
        # ログインユーザー：
        try:
            # 削除対象ルームがDBか一時保存かを解決しつつ、権限を確認
            # Resolve room storage location and validate user access permissions
            room_mode, legacy_response = await _resolve_authenticated_room_mode(
                session["user_id"],
                room_id,
                "他ユーザーのチャットルームは削除できません",
            )
            if legacy_response is not None:
                return legacy_response
                
            # 一時ルームの場合、エフェメラルストアから削除
            # Delete temporary room from ephemeral store
            if room_mode == "temporary":
                temporary_sid = get_temporary_user_store_key(session["user_id"])
                deleted = await run_blocking(ephemeral_store.delete_room, temporary_sid, room_id)
                if not deleted:
                    return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
                return jsonify({"message": "未保存チャットを削除しました"}, status_code=200)

            # DB内の通常ルームの場合、履歴を含めトランザクション削除
            # Delete database room and history atomically
            response_payload = await _delete_room_for_user(room_id, session["user_id"])
            return jsonify(response_payload, status_code=200)
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to delete chat room for authenticated user.",
            )
    else:
        # ゲストユーザー：
        sid = get_session_id(session)
        # エフェメラルストアからルームを削除
        # Delete room from guest ephemeral store
        if not await run_blocking(ephemeral_store.delete_room, sid, room_id):
            return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
        # セッションからゲスト用ルームの登録を削除
        # Deregister guest room from active guest session
        unregister_guest_room(session, room_id)
        return jsonify({"message": "エフェメラルチャットルームを削除しました"}, status_code=200)


# 複数のチャットルームを一括削除するAPIエンドポイント
# API endpoint to bulk delete multiple chat rooms.
@chat_bp.post("/api/delete_chat_rooms", name="chat.delete_chat_rooms")
async def delete_chat_rooms(request: Request):
    """
    ログインユーザーが所有する複数のチャットルームを一括で削除します。
    Bulk deletes multiple chat rooms owned by the active authenticated user.
    """
    await run_blocking(cleanup_ephemeral_chats)
    
    # リクエストデータ取得
    # Extract request payload
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # ルームIDリストのスキーマ検証
    # Validate target room IDs payload
    payload, validation_error = validate_payload_model(
        data,
        ChatRoomIdsRequest,
        error_message="room_ids is required",
    )
    if validation_error is not None:
        return validation_error

    session = request.session
    # ログインしていない場合は拒否
    # Require authentication for bulk delete actions
    if "user_id" not in session:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # 一括削除処理を呼び出す
        # Dispatch the database bulk deletion logic
        response_payload = await _delete_rooms_for_user(payload.room_ids, session["user_id"])
        return jsonify(response_payload, status_code=200)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to bulk delete chat rooms for authenticated user.",
        )


# チャットルームの名前を変更するAPIエンドポイント
# API endpoint to rename an existing chat room.
@chat_bp.post("/api/rename_chat_room", name="chat.rename_chat_room")
async def rename_chat_room(request: Request):
    """
    指定されたチャットルームのタイトルを変更します。
    Renames the title of the specified chat room.
    """
    await run_blocking(cleanup_ephemeral_chats)
    
    # リクエストパース
    # Parse request payload
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # パラメータ検証
    # Validate rename payload model
    payload, validation_error = validate_payload_model(
        data,
        RenameChatRoomRequest,
        error_message="room_id と new_title が必要です",
    )
    if validation_error is not None:
        return validation_error

    room_id = payload.room_id
    new_title = payload.new_title

    session = request.session
    if "user_id" in session:
        # ログインユーザー：
        try:
            # 所有権とストレージ（DBまたは一時ストア）の解決
            # Verify owner permissions and storage type (DB or ephemeral)
            room_mode, legacy_response = await _resolve_authenticated_room_mode(
                session["user_id"],
                room_id,
                "他ユーザーのチャットルームは変更できません",
            )
            if legacy_response is not None:
                return legacy_response

            # 一時チャットルームの名称変更
            # Rename unsaved temporary room in ephemeral store
            if room_mode == "temporary":
                temporary_sid = get_temporary_user_store_key(session["user_id"])
                renamed = await run_blocking(ephemeral_store.rename_room, temporary_sid, room_id, new_title)
                if not renamed:
                    return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
            # 永続ルームの名称変更をDBに反映
            # Rename database room title
            else:
                await rename_chat_room_in_db(room_id, new_title)
            return jsonify({"message": "ルーム名を変更しました"}, status_code=200)
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to rename chat room for authenticated user.",
            )
    else:
        # 非ログインユーザー（ゲスト）：エフェメラルストアのルーム名を変更
        # Guests: Rename room within the ephemeral guest store
        sid = get_session_id(session)
        if not await run_blocking(ephemeral_store.rename_room, sid, room_id, new_title):
            return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
        return jsonify({"message": "ルーム名を変更しました"}, status_code=200)


# チャットルーム共有用トークンおよびURLを生成するAPIエンドポイント
# API endpoint to generate a share token and link for a room.
@chat_bp.post("/api/share_chat_room", name="chat.share_chat_room")
async def share_chat_room(request: Request):
    """
    チャットルームを他人に共有するための共有トークンとURLを生成します（ログインユーザーの通常ルームのみ共有可能）。
    Generates a share token and URL to share the chat room (only normal persisted rooms can be shared).
    """
    await run_blocking(cleanup_ephemeral_chats)
    
    # リクエストデータ取得
    # Extract request payload
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # スキーマ検証
    # Validate share payload model
    payload, validation_error = validate_payload_model(
        data,
        ShareChatRoomRequest,
        error_message="room_id is required",
    )
    if validation_error is not None:
        return validation_error

    user_id = request.session.get("user_id")
    # ログインしていない場合は共有不可
    # Authenticated user session required for sharing
    if not user_id:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)

    room_id = payload.room_id
    try:
        # ルームが所有者のものか、および一時ルームではないか検証
        # Verify ownership of room and ensure it is not temporary
        room_mode, legacy_response = await _resolve_authenticated_room_mode(
            user_id,
            room_id,
            "他ユーザーのチャットルームは共有できません",
        )
        if legacy_response is not None:
            return legacy_response
        if room_mode == "temporary":
            return jsonify({"error": "temporary chat は共有できません"}, status_code=400)

        # 共有トークンの生成または既存トークンの取得
        # Create a new shared chat token or fetch the existing one from database
        share_token_result = await create_or_get_shared_chat_token(room_id, user_id)
        if isinstance(share_token_result, tuple) and len(share_token_result) == 2:
            share_token, status_code = share_token_result
            if status_code == 404 or not share_token:
                return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
        else:
            share_token = share_token_result

        # フルURLを生成
        # Generate the full frontend URL for sharing
        share_url = build_public_share_url("chat", share_token)
        return jsonify(
            {
                "share_token": share_token,
                "share_url": share_url,
            }
        )
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to create share link for chat room.",
        )


# 共有トークンを用いて共有チャットルームの内容を取得するAPIエンドポイント
# API endpoint to retrieve a shared chat room's content using its share token.
@chat_bp.get("/api/shared_chat_room", name="chat.shared_chat_room")
async def shared_chat_room(request: Request):
    """
    共有トークンをもとに、パブリックに共有されたチャットルームのタイトルとメッセージ履歴を取得します。
    Retrieves the title and message history of a publicly shared chat room via its share token.
    """
    await run_blocking(cleanup_ephemeral_chats)
    
    # トークンをクエリパラメータから取得
    # Extract the token query parameter
    token = (request.query_params.get("token") or "").strip()
    if not token:
        return jsonify({"error": ERROR_TOKEN_REQUIRED}, status_code=400)

    try:
        # トークンに紐づくルームデータと履歴を取得
        # Retrieve the shared room payload using the share token
        payload_result = await get_shared_chat_room_payload(token)
        if isinstance(payload_result, tuple) and len(payload_result) == 2:
            payload, status_code = payload_result
            return jsonify(payload, status_code=status_code or 200)
        return jsonify(payload_result, status_code=200)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to fetch shared chat room payload.",
        )


# 共有チャットを閲覧者自身のチャットとして複製するAPIエンドポイント
# API endpoint that forks a shared chat into a chat room owned by the viewer.
@chat_bp.post("/api/fork_shared_chat_room", name="chat.fork_shared_chat_room")
async def fork_shared_chat_room(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
):
    """
    共有チャットの会話を複製し、閲覧者が続きを話せる自分のチャットルームを作成します。
    共有元のルームは読み取り専用のまま変更されません。
    Copies a shared conversation into a chat room owned by the viewer so they can continue it.
    The shared source room stays read-only and is never modified.
    """
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    await run_blocking(cleanup_ephemeral_chats)

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ForkSharedChatRoomRequest,
        error_message=ERROR_TOKEN_REQUIRED,
    )
    if validation_error is not None:
        return validation_error

    token = payload.token
    room_id = payload.id
    session = request.session

    try:
        if "user_id" in session:
            # ログインユーザーは自分の通常ルームとしてDBに永続化する
            # Authenticated viewers get a persisted normal room of their own.
            result = await fork_shared_chat_into_db_room(
                token,
                room_id,
                session["user_id"],
            )
            return jsonify(result, status_code=201)

        # 非ログインユーザーもそのまま続きを話せるようにするが、ゲストの日次上限は
        # 新規ルーム作成と同じ基準で消費する
        # Guests can continue too, but the fork consumes the same daily quota as creating a room.
        allowed, message = await run_blocking(
            consume_guest_chat_daily_limit,
            request,
            service=resolved_auth_limit_service,
        )
        if not allowed:
            return jsonify_rate_limited(
                message or "1日10回までです",
                retry_after=get_seconds_until_tomorrow(),
            )

        sid = get_session_id(session)
        result = await _fork_shared_chat_into_ephemeral_room(token, sid, room_id)
        register_guest_room(session, room_id)
        return jsonify(result, status_code=201)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to fork shared chat room.",
        )
