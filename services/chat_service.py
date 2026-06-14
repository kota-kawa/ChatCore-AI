import secrets
from typing import Any

from .db import get_db_connection, is_retryable_db_error, rollback_connection
from .repositories.chat_repository import ChatRepository


# 日本語: get chat repository の取得処理を担当します。
# English: Handle fetching for get chat repository.
def _get_chat_repository() -> ChatRepository:
    return ChatRepository(
        connection_getter=get_db_connection,
        retryable_error_checker=is_retryable_db_error,
        rollback=rollback_connection,
        token_generator=secrets.token_urlsafe,
    )


# 日本語: save message to db の保存処理を担当します。
# English: Handle saving for save message to db.
def save_message_to_db(
    chat_room_id: str,
    message: str,
    sender: str,
    attached_file_names: list[str] | None = None,
    parent_id: int | None = None,
    message_parts: list[dict[str, Any]] | None = None,
    attached_file_contents: list[Any] | None = None,
) -> int | None:
    return _get_chat_repository().save_message(
        chat_room_id,
        message,
        sender,
        attached_file_names,
        parent_id,
        message_parts,
        attached_file_contents,
    )


# 日本語: get active path の取得処理を担当します。
# English: Handle fetching for get active path.
def get_active_path(
    chat_room_id: str,
    *,
    include_attachment_contents: bool = False,
) -> list[dict[str, Any]]:
    return _get_chat_repository().get_active_path(
        chat_room_id,
        include_attachment_contents=include_attachment_contents,
    )


# 日本語: get active leaf id の取得処理を担当します。
# English: Handle fetching for get active leaf id.
def get_active_leaf_id(chat_room_id: str) -> int | None:
    return _get_chat_repository().get_active_leaf_id(chat_room_id)


# 日本語: switch chat branch に関する処理の入口です。
# English: Entry point for logic related to switch chat branch.
def switch_chat_branch(chat_room_id: str, target_id: int) -> list[dict[str, Any]]:
    return _get_chat_repository().switch_branch(chat_room_id, target_id)


# 日本語: create chat room in db の作成処理を担当します。
# English: Handle creating for create chat room in db.
def create_chat_room_in_db(room_id: str, user_id: int, title: str, mode: str = "normal") -> None:
    return _get_chat_repository().create_room(room_id, user_id, title, mode)


# 日本語: delete chat room if no assistant messages の削除処理を担当します。
# English: Handle deleting for delete chat room if no assistant messages.
def delete_chat_room_if_no_assistant_messages(room_id: str, user_id: int) -> bool:
    return _get_chat_repository().delete_room_if_no_assistant_messages(room_id, user_id)


# 日本語: truncate chat room for edit に関する処理の入口です。
# English: Entry point for logic related to truncate chat room for edit.
def truncate_chat_room_for_edit(chat_room_id: str, trailing_user_count: int) -> bool:
    return _get_chat_repository().delete_messages_from_trailing_user_count(chat_room_id, trailing_user_count)


# 日本語: delete last assistant message from db の削除処理を担当します。
# English: Handle deleting for delete last assistant message from db.
def delete_last_assistant_message_from_db(chat_room_id: str) -> bool:
    return _get_chat_repository().delete_last_assistant_message(chat_room_id)


# 日本語: rename chat room in db に関する処理の入口です。
# English: Entry point for logic related to rename chat room in db.
def rename_chat_room_in_db(room_id: str, new_title: str) -> None:
    return _get_chat_repository().rename_room(room_id, new_title)


# 日本語: rename chat room if current title in に関する処理の入口です。
# English: Entry point for logic related to rename chat room if current title in.
def rename_chat_room_if_current_title_in(
    room_id: str,
    new_title: str,
    allowed_current_titles: list[str],
) -> bool:
    return _get_chat_repository().rename_room_if_current_title_in(
        room_id,
        new_title,
        allowed_current_titles,
    )


# 日本語: get chat room messages の取得処理を担当します。
# English: Handle fetching for get chat room messages.
def get_chat_room_messages(chat_room_id: str) -> list[dict[str, str]]:
    return _get_chat_repository().get_room_messages_for_llm(chat_room_id)


# 日本語: validate room owner の検証処理を担当します。
# English: Handle validating for validate room owner.
def validate_room_owner(
    room_id: str, user_id: int, forbidden_message: str
) -> str | None:
    return _get_chat_repository().validate_room_owner(room_id, user_id, forbidden_message)


# 日本語: create or get shared chat token の作成処理を担当します。
# English: Handle creating for create or get shared chat token.
def create_or_get_shared_chat_token(room_id: str, user_id: int) -> str:
    return _get_chat_repository().create_or_get_shared_chat_token(room_id, user_id)


# 日本語: get shared chat room payload の取得処理を担当します。
# English: Handle fetching for get shared chat room payload.
def get_shared_chat_room_payload(
    token: str,
) -> dict[str, Any]:
    return _get_chat_repository().get_shared_chat_room_payload(token)
