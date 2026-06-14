import secrets
from typing import Any

from .db import get_db_connection, is_retryable_db_error, rollback_connection
from .repositories.chat_repository import ChatRepository


# チャットリポジトリのインスタンスを作成して返す
# Create and return an instance of the ChatRepository
def _get_chat_repository() -> ChatRepository:
    return ChatRepository(
        connection_getter=get_db_connection,
        retryable_error_checker=is_retryable_db_error,
        rollback=rollback_connection,
        token_generator=secrets.token_urlsafe,
    )


# メッセージをデータベースに保存する
# Save a message to the database
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


# チャットルームのアクティブな対話パス（履歴）を取得する
# Retrieve the active interaction path (history) of the chat room
def get_active_path(
    chat_room_id: str,
    *,
    include_attachment_contents: bool = False,
) -> list[dict[str, Any]]:
    return _get_chat_repository().get_active_path(
        chat_room_id,
        include_attachment_contents=include_attachment_contents,
    )


# アクティブなリーフメッセージのIDを取得する
# Retrieve the ID of the active leaf message
def get_active_leaf_id(chat_room_id: str) -> int | None:
    return _get_chat_repository().get_active_leaf_id(chat_room_id)


# 指定したメッセージIDのブランチに切り替える
# Switch the active path to the branch of the specified message ID
def switch_chat_branch(chat_room_id: str, target_id: int) -> list[dict[str, Any]]:
    return _get_chat_repository().switch_branch(chat_room_id, target_id)


# チャットルームをデータベースに新規作成する
# Create a new chat room in the database
def create_chat_room_in_db(room_id: str, user_id: int, title: str, mode: str = "normal") -> None:
    return _get_chat_repository().create_room(room_id, user_id, title, mode)


# アシスタントからの応答が1つもない場合、チャットルームを削除する
# Delete the chat room if it contains no assistant messages
def delete_chat_room_if_no_assistant_messages(room_id: str, user_id: int) -> bool:
    return _get_chat_repository().delete_room_if_no_assistant_messages(room_id, user_id)


# メッセージ編集のために、指定した件数以降のユーザーメッセージ等を切り詰める
# Truncate messages starting from a trailing user message count for editing
def truncate_chat_room_for_edit(chat_room_id: str, trailing_user_count: int) -> bool:
    return _get_chat_repository().delete_messages_from_trailing_user_count(chat_room_id, trailing_user_count)


# 最後のメッセージがアシスタントのものである場合、データベースから削除する
# Delete the last message from the database if it was sent by the assistant
def delete_last_assistant_message_from_db(chat_room_id: str) -> bool:
    return _get_chat_repository().delete_last_assistant_message(chat_room_id)


# チャットルームのタイトルを変更する
# Rename the title of the chat room
def rename_chat_room_in_db(room_id: str, new_title: str) -> None:
    return _get_chat_repository().rename_room(room_id, new_title)


# 現在のタイトルが許可リストに含まれる場合のみ、チャットルーム名を変更する
# Rename the chat room only if its current title is in the allowed list
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


# LLM送信向けにチャットルームのメッセージ履歴を取得する
# Retrieve the message history of the chat room formatted for the LLM
def get_chat_room_messages(chat_room_id: str) -> list[dict[str, str]]:
    return _get_chat_repository().get_room_messages_for_llm(chat_room_id)


# ルームの所有者（作成ユーザー）を検証する
# Validate the owner (creator) of the chat room
def validate_room_owner(
    room_id: str, user_id: int, forbidden_message: str
) -> str | None:
    return _get_chat_repository().validate_room_owner(room_id, user_id, forbidden_message)


# 共有用トークンを生成または取得する
# Generate or retrieve a token for sharing the chat room
def create_or_get_shared_chat_token(room_id: str, user_id: int) -> str:
    return _get_chat_repository().create_or_get_shared_chat_token(room_id, user_id)


# 共有されたチャットルームのデータペイロードを取得する
# Retrieve the data payload of the shared chat room
def get_shared_chat_room_payload(
    token: str,
) -> dict[str, Any]:
    return _get_chat_repository().get_shared_chat_room_payload(token)
