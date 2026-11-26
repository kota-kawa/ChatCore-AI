"""チャットルームの現在名を所有者に返す。Read the current chat room title for its owner."""

import logging

from fastapi import Request

from services.api_errors import ApiServiceError
from services.chat_title import get_owned_chat_room_title
from services.error_messages import ERROR_CHAT_ROOM_ID_REQUIRED, ERROR_CHAT_ROOM_NOT_FOUND
from services.response_models import ChatRoomTitleResponse
from services.web import jsonify, jsonify_service_error, log_and_internal_server_error

from . import chat_bp

logger = logging.getLogger(__name__)


@chat_bp.get("/api/chat_room_title", name="chat.chat_room_title")
async def chat_room_title(request: Request):
    """タイトル生成を遅延したクライアントに、所有する通常ルームの現在名を返す。

    Return the current title of an owned persistent room to clients following up on deferred titling.
    """
    room_id = request.query_params.get("room_id")
    if not room_id:
        return jsonify({"error": ERROR_CHAT_ROOM_ID_REQUIRED}, status_code=400)
    user_id = request.session.get("user_id")
    headers = {"Cache-Control": "no-store"}
    try:
        title = await get_owned_chat_room_title(room_id, user_id) if user_id is not None else None
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to fetch current chat room title.")
    if title is None:
        return jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404, headers=headers)
    return jsonify(ChatRoomTitleResponse(title=title).model_dump(), headers=headers)
