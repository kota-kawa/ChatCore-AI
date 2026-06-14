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
from services.db import get_db_connection
from services.chat_service import (
    create_or_get_shared_chat_token,
    create_chat_room_in_db,
    get_shared_chat_room_payload,
    rename_chat_room_in_db,
    validate_room_owner,
)
from services.datetime_serialization import serialize_datetime_iso

from services.request_models import (
    ChatRoomIdRequest,
    ChatRoomIdsRequest,
    NewChatRoomRequest,
    RenameChatRoomRequest,
    ShareChatRoomRequest,
)
from services.web import (
    frontend_url,
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

CHAT_ROOMS_DEFAULT_PAGE_SIZE = 20
CHAT_ROOMS_MAX_PAGE_SIZE = 100


# 日本語: resolve auth limit service に関する処理の入口です。
# English: Entry point for logic related to resolve auth limit service.
def _resolve_auth_limit_service(
    request: Request,
    service: AuthLimitService | None,
) -> AuthLimitService:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(service, AuthLimitService):
        return service
    return get_auth_limit_service(request)


# 日本語: parse positive int の解析処理を担当します。
# English: Handle parsing for parse positive int.
def _parse_positive_int(value: str | None, default: int, maximum: int) -> int:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if value is None:
        return default
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(1, parsed), maximum)


# 日本語: resolve room list pagination に関する処理の入口です。
# English: Entry point for logic related to resolve room list pagination.
def _resolve_room_list_pagination(request: Request) -> tuple[int, tuple[datetime, str] | None]:
    limit = _parse_positive_int(
        request.query_params.get("limit"),
        CHAT_ROOMS_DEFAULT_PAGE_SIZE,
        CHAT_ROOMS_MAX_PAGE_SIZE,
    )
    cursor = _decode_room_list_cursor(request.query_params.get("cursor"))
    return limit, cursor


# 日本語: decode room list cursor に関する処理の入口です。
# English: Entry point for logic related to decode room list cursor.
def _decode_room_list_cursor(value: str | None) -> tuple[datetime, str] | None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not value:
        return None
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
        created_at = payload.get("created_at")
        room_id = payload.get("id")
        if not isinstance(created_at, str) or not isinstance(room_id, str) or not room_id:
            raise ValueError
        normalized_created_at = created_at.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized_created_at), room_id
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        raise ApiServiceError("invalid cursor", 400)


# 日本語: encode room list cursor に関する処理の入口です。
# English: Entry point for logic related to encode room list cursor.
def _encode_room_list_cursor(room: dict[str, Any]) -> str | None:
    created_at = room.get("created_at")
    room_id = room.get("id")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(created_at, str) or not isinstance(room_id, str) or not room_id:
        return None
    payload = json.dumps(
        {"created_at": created_at, "id": room_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


# 日本語: fetch persisted user rooms の取得処理を担当します。
# English: Handle fetching for fetch persisted user rooms.
def _fetch_persisted_user_rooms(
    user_id: int,
    *,
    limit: int | None = None,
    cursor: tuple[datetime, str] | None = None,
) -> list[dict[str, Any]]:
    # 永続保存されたチャットルーム一覧のみを取得する
    # Fetch only persisted chat rooms ordered by newest first.
    conn = None
    db_cursor = None
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        conn = get_db_connection()
        db_cursor = conn.cursor()
        query = """
            SELECT id, title, COALESCE(mode, 'normal'), created_at
            FROM chat_rooms
            WHERE user_id = %s
              AND COALESCE(mode, 'normal') <> 'temporary'
        """
        params: list[Any] = [user_id]
        if cursor is not None:
            query = f"{query} AND (created_at, id) < (%s, %s)"
            params.extend([cursor[0], cursor[1]])
        query = f"{query} ORDER BY created_at DESC, id DESC"
        if limit is not None:
            query = f"{query} LIMIT %s"
            params.append(limit)
        db_cursor.execute(query, tuple(params))
        rows = db_cursor.fetchall()
        rooms = []
        for (room_id, title, mode, created_at) in rows:
            rooms.append(
                {
                    "id": room_id,
                    "title": title,
                    "mode": mode or "normal",
                    "created_at": serialize_datetime_iso(created_at),
                }
            )
        return rooms
    finally:
        if db_cursor is not None:
            db_cursor.close()
        if conn is not None:
            conn.close()


# 日本語: fetch temporary user rooms の取得処理を担当します。
# English: Handle fetching for fetch temporary user rooms.
def _fetch_temporary_user_rooms(user_id: int) -> list[dict[str, Any]]:
    temporary_sid = get_temporary_user_store_key(user_id)
    rooms = ephemeral_store.list_rooms(temporary_sid)
    return [
        {
            "id": str(room.get("id") or ""),
            "title": str(room.get("title") or "新規チャット"),
            "mode": "temporary",
            "created_at": str(room.get("created_at") or ""),
        }
        for room in rooms
        if room.get("id")
    ]


# 日本語: sort rooms newest first に関する処理の入口です。
# English: Entry point for logic related to sort rooms newest first.
def _sort_rooms_newest_first(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rooms,
        key=lambda room: str(room.get("created_at") or ""),
        reverse=True,
    )


# 日本語: resolve authenticated room mode に関する処理の入口です。
# English: Entry point for logic related to resolve authenticated room mode.
def _resolve_authenticated_room_mode(
    user_id: int,
    room_id: str,
    forbidden_message: str,
) -> tuple[str | None, Any]:
    temporary_sid = get_temporary_user_store_key(user_id)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if ephemeral_store.room_exists(temporary_sid, room_id):
        return "temporary", None

    owner_result = validate_room_owner(room_id, user_id, forbidden_message)
    legacy_response = _legacy_error_response(owner_result)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if legacy_response is not None:
        return None, legacy_response
    return str(owner_result or "normal"), None


# 日本語: delete room for user の削除処理を担当します。
# English: Handle deleting for delete room for user.
def _delete_room_for_user(room_id: str, user_id: int) -> dict[str, str]:
    # 所有者確認後に履歴→ルームの順で削除し、整合性を保つ
    # Validate owner, then delete history and room to keep data consistent.
    conn = None
    cursor = None
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        check_q = "SELECT user_id FROM chat_rooms WHERE id = %s"
        cursor.execute(check_q, (room_id,))
        result = cursor.fetchone()
        if not result:
            raise ApiServiceError(ERROR_CHAT_ROOM_NOT_FOUND, 404)
        if result[0] != user_id:
            raise ApiServiceError("他ユーザーのチャットルームは削除できません", 403)

        del_history_q = "DELETE FROM chat_history WHERE chat_room_id = %s"
        cursor.execute(del_history_q, (room_id,))
        del_room_q = "DELETE FROM chat_rooms WHERE id = %s"
        cursor.execute(del_room_q, (room_id,))
        conn.commit()
        return {"message": "削除しました"}
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 日本語: unique room ids に関する処理の入口です。
# English: Entry point for logic related to unique room ids.
def _unique_room_ids(room_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(room_ids))


# 日本語: placeholders に関する処理の入口です。
# English: Entry point for logic related to placeholders.
def _placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)


# 日本語: delete rooms for user の削除処理を担当します。
# English: Handle deleting for delete rooms for user.
def _delete_rooms_for_user(room_ids: list[str], user_id: int) -> dict[str, Any]:
    # 一括削除は全IDの所有者確認後に実行し、部分削除を避ける
    # Validate every room before deleting so bulk actions do not partially apply.
    unique_room_ids = _unique_room_ids(room_ids)
    conn = None
    cursor = None
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholders = _placeholders(len(unique_room_ids))
        cursor.execute(
            f"SELECT id, user_id FROM chat_rooms WHERE id IN ({placeholders})",
            tuple(unique_room_ids),
        )
        rows = cursor.fetchall()
        found_by_id = {str(room_id): owner_id for room_id, owner_id in rows}

        if len(found_by_id) != len(unique_room_ids):
            raise ApiServiceError(ERROR_CHAT_ROOM_NOT_FOUND, 404)
        if any(owner_id != user_id for owner_id in found_by_id.values()):
            raise ApiServiceError("他ユーザーのチャットルームは削除できません", 403)

        cursor.execute(
            f"DELETE FROM chat_history WHERE chat_room_id IN ({placeholders})",
            tuple(unique_room_ids),
        )
        cursor.execute(
            f"DELETE FROM chat_rooms WHERE id IN ({placeholders})",
            tuple(unique_room_ids),
        )
        conn.commit()
        return {
            "message": "削除しました",
            "deleted_count": len(unique_room_ids),
            "deleted_room_ids": unique_room_ids,
        }
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 日本語: legacy error response に関する処理の入口です。
# English: Entry point for logic related to legacy error response.
def _legacy_error_response(result: Any):
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not (isinstance(result, tuple) and len(result) == 2):
        return None
    payload, status_code = result
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if payload is None:
        return None
    if isinstance(payload, dict) and isinstance(status_code, int):
        return jsonify(payload, status_code=status_code)
    return None


# 日本語: new chat room に関する処理の入口です。
# English: Entry point for logic related to new chat room.
@chat_bp.post("/api/new_chat_room", name="chat.new_chat_room")
async def new_chat_room(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        NewChatRoomRequest,
        error_message="'id' フィールドが必要です。",
    )
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if validation_error is not None:
        return validation_error

    room_id = payload.id
    title = payload.title
    mode = payload.mode

    session = request.session
    if "user_id" in session:
        # ログインユーザーは通常ルームだけ DB 永続化し、temporary は一時ストアだけで扱う
        # Persist only normal rooms for authenticated users; keep temporary rooms ephemeral.
        user_id = session["user_id"]
        try:
            if mode == "temporary":
                temporary_sid = get_temporary_user_store_key(user_id)
                await run_blocking(ephemeral_store.create_room, temporary_sid, room_id, title)
            else:
                await run_blocking(create_chat_room_in_db, room_id, user_id, title, mode)
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
        # 非ログインユーザーはサーバー側の日次カウンタで回数制限する
        # Enforce guest daily quota with a server-side counter.
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
        await run_blocking(ephemeral_store.create_room, sid, room_id, title)
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


# 日本語: get chat rooms の取得処理を非同期で担当します。
# English: Handle fetching for get chat rooms asynchronously.
@chat_bp.get("/api/get_chat_rooms", name="chat.get_chat_rooms")
async def get_chat_rooms(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    session = request.session
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "user_id" in session:
        # ログインユーザー：DBから取得
        # Authenticated users read room list from DB.
        user_id = session["user_id"]
        try:
            limit, cursor = _resolve_room_list_pagination(request)
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        fetch_limit = limit + 1
        try:
            persisted_rooms = await run_blocking(
                _fetch_persisted_user_rooms,
                user_id,
                limit=fetch_limit,
                cursor=cursor,
            )
            has_more = len(persisted_rooms) > limit
            persisted_rooms = persisted_rooms[:limit]
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


# 日本語: delete chat room の削除処理を非同期で担当します。
# English: Handle deleting for delete chat room asynchronously.
@chat_bp.post("/api/delete_chat_room", name="chat.delete_chat_room")
async def delete_chat_room(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ChatRoomIdRequest,
        error_message="room_id is required",
    )
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if validation_error is not None:
        return validation_error

    room_id = payload.room_id

    session = request.session
    if "user_id" in session:
        try:
            room_mode, legacy_response = await run_blocking(
                _resolve_authenticated_room_mode,
                session["user_id"],
                room_id,
                "他ユーザーのチャットルームは削除できません",
            )
            if legacy_response is not None:
                return legacy_response
            if room_mode == "temporary":
                temporary_sid = get_temporary_user_store_key(session["user_id"])
                deleted = await run_blocking(ephemeral_store.delete_room, temporary_sid, room_id)
                if not deleted:
                    return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
                return jsonify({"message": "未保存チャットを削除しました"}, status_code=200)

            response_payload = await run_blocking(_delete_room_for_user, room_id, session["user_id"])
            return jsonify(response_payload, status_code=200)
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to delete chat room for authenticated user.",
            )
    else:
        sid = get_session_id(session)
        if not await run_blocking(ephemeral_store.delete_room, sid, room_id):
            return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
        unregister_guest_room(session, room_id)
        return jsonify({"message": "エフェメラルチャットルームを削除しました"}, status_code=200)


# 日本語: delete chat rooms の削除処理を非同期で担当します。
# English: Handle deleting for delete chat rooms asynchronously.
@chat_bp.post("/api/delete_chat_rooms", name="chat.delete_chat_rooms")
async def delete_chat_rooms(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ChatRoomIdsRequest,
        error_message="room_ids is required",
    )
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if validation_error is not None:
        return validation_error

    session = request.session
    if "user_id" not in session:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        response_payload = await run_blocking(
            _delete_rooms_for_user,
            payload.room_ids,
            session["user_id"],
        )
        return jsonify(response_payload, status_code=200)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to bulk delete chat rooms for authenticated user.",
        )


# 日本語: rename chat room に関する処理の入口です。
# English: Entry point for logic related to rename chat room.
@chat_bp.post("/api/rename_chat_room", name="chat.rename_chat_room")
async def rename_chat_room(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        RenameChatRoomRequest,
        error_message="room_id と new_title が必要です",
    )
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if validation_error is not None:
        return validation_error

    room_id = payload.room_id
    new_title = payload.new_title

    session = request.session
    if "user_id" in session:
        try:
            room_mode, legacy_response = await run_blocking(
                _resolve_authenticated_room_mode,
                session["user_id"],
                room_id,
                "他ユーザーのチャットルームは変更できません",
            )
            if legacy_response is not None:
                return legacy_response

            if room_mode == "temporary":
                temporary_sid = get_temporary_user_store_key(session["user_id"])
                renamed = await run_blocking(ephemeral_store.rename_room, temporary_sid, room_id, new_title)
                if not renamed:
                    return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
            else:
                await run_blocking(rename_chat_room_in_db, room_id, new_title)
            return jsonify({"message": "ルーム名を変更しました"}, status_code=200)
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to rename chat room for authenticated user.",
            )
    else:
        sid = get_session_id(session)
        if not await run_blocking(ephemeral_store.rename_room, sid, room_id, new_title):
            return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
        return jsonify({"message": "ルーム名を変更しました"}, status_code=200)


# 日本語: share chat room に関する処理の入口です。
# English: Entry point for logic related to share chat room.
@chat_bp.post("/api/share_chat_room", name="chat.share_chat_room")
async def share_chat_room(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ShareChatRoomRequest,
        error_message="room_id is required",
    )
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if validation_error is not None:
        return validation_error

    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)

    room_id = payload.room_id
    try:
        room_mode, legacy_response = await run_blocking(
            _resolve_authenticated_room_mode,
            user_id,
            room_id,
            "他ユーザーのチャットルームは共有できません",
        )
        if legacy_response is not None:
            return legacy_response
        if room_mode == "temporary":
            return jsonify({"error": "temporary chat は共有できません"}, status_code=400)

        share_token_result = await run_blocking(create_or_get_shared_chat_token, room_id, user_id)
        if isinstance(share_token_result, tuple) and len(share_token_result) == 2:
            share_token, status_code = share_token_result
            if status_code == 404 or not share_token:
                return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)
        else:
            share_token = share_token_result

        share_url = frontend_url(f"/shared/{share_token}")
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


# 日本語: shared chat room に関する処理の入口です。
# English: Entry point for logic related to shared chat room.
@chat_bp.get("/api/shared_chat_room", name="chat.shared_chat_room")
async def shared_chat_room(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    token = (request.query_params.get("token") or "").strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not token:
        return jsonify({"error": ERROR_TOKEN_REQUIRED}, status_code=400)

    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        payload_result = await run_blocking(get_shared_chat_room_payload, token)
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
