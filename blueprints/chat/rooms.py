import logging
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


def _resolve_auth_limit_service(
    request: Request,
    service: AuthLimitService | None,
) -> AuthLimitService:
    if isinstance(service, AuthLimitService):
        return service
    return get_auth_limit_service(request)


def _fetch_user_rooms(user_id: int) -> list[dict[str, Any]]:
    # 認証ユーザーのチャットルーム一覧を新しい順で取得する
    # Fetch authenticated user's chat rooms ordered by newest first.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT id, title, COALESCE(mode, 'normal'), created_at
            FROM chat_rooms
            WHERE user_id = %s
            ORDER BY created_at DESC
        """
        cursor.execute(query, (user_id,))
        rows = cursor.fetchall()
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
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _delete_room_for_user(room_id: str, user_id: int) -> dict[str, str]:
    # 所有者確認後に履歴→ルームの順で削除し、整合性を保つ
    # Validate owner, then delete history and room to keep data consistent.
    conn = None
    cursor = None
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


def _legacy_error_response(result: Any):
    if not (isinstance(result, tuple) and len(result) == 2):
        return None
    payload, status_code = result
    if payload is None:
        return None
    if isinstance(payload, dict) and isinstance(status_code, int):
        return jsonify(payload, status_code=status_code)
    return None


@chat_bp.post("/api/new_chat_room", name="chat.new_chat_room")
async def new_chat_room(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

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

    session = request.session
    if "user_id" in session:
        # ログインユーザーの場合はDBに保存（利用回数制限なし）
        # Persist for authenticated users in DB without daily free limit.
        user_id = session["user_id"]
        try:
            await run_blocking(create_chat_room_in_db, room_id, user_id, title, mode)
            if mode == "temporary":
                temporary_sid = get_temporary_user_store_key(user_id)
                await run_blocking(ephemeral_store.create_room, temporary_sid, room_id, title)
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


@chat_bp.get("/api/get_chat_rooms", name="chat.get_chat_rooms")
async def get_chat_rooms(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    session = request.session
    if "user_id" in session:
        # ログインユーザー：DBから取得
        # Authenticated users read room list from DB.
        user_id = session["user_id"]
        try:
            rooms = await run_blocking(_fetch_user_rooms, user_id)
            return jsonify({"rooms": rooms})
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to fetch chat rooms for authenticated user.",
            )
    else:
        # 非ログインユーザーにはサイドバー上でチャットルーム一覧は表示しない
        # Do not show sidebar room list for guests.
        return jsonify({"rooms": []})


@chat_bp.post("/api/delete_chat_room", name="chat.delete_chat_room")
async def delete_chat_room(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

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
        try:
            room_mode = await run_blocking(
                validate_room_owner,
                room_id,
                session["user_id"],
                "他ユーザーのチャットルームは削除できません",
            )
            response_payload = await run_blocking(_delete_room_for_user, room_id, session["user_id"])
            if room_mode == "temporary":
                temporary_sid = get_temporary_user_store_key(session["user_id"])
                await run_blocking(ephemeral_store.delete_room, temporary_sid, room_id)
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


@chat_bp.post("/api/rename_chat_room", name="chat.rename_chat_room")
async def rename_chat_room(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

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
        try:
            owner_result = await run_blocking(
                validate_room_owner,
                room_id,
                session["user_id"],
                "他ユーザーのチャットルームは変更できません",
            )
            legacy_response = _legacy_error_response(owner_result)
            if legacy_response is not None:
                return legacy_response

            await run_blocking(rename_chat_room_in_db, room_id, new_title)
            if owner_result == "temporary":
                temporary_sid = get_temporary_user_store_key(session["user_id"])
                await run_blocking(ephemeral_store.rename_room, temporary_sid, room_id, new_title)
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


@chat_bp.post("/api/share_chat_room", name="chat.share_chat_room")
async def share_chat_room(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ShareChatRoomRequest,
        error_message="room_id is required",
    )
    if validation_error is not None:
        return validation_error

    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)

    room_id = payload.room_id
    try:
        owner_result = await run_blocking(
            validate_room_owner,
            room_id,
            user_id,
            "他ユーザーのチャットルームは共有できません",
        )
        legacy_response = _legacy_error_response(owner_result)
        if legacy_response is not None:
            return legacy_response
        if owner_result == "temporary":
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


@chat_bp.get("/api/shared_chat_room", name="chat.shared_chat_room")
async def shared_chat_room(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    token = (request.query_params.get("token") or "").strip()
    if not token:
        return jsonify({"error": ERROR_TOKEN_REQUIRED}, status_code=400)

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
