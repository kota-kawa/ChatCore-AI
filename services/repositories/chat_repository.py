from __future__ import annotations

import json
import secrets
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.attached_files import decode_attached_files_from_storage, encode_attached_files_for_storage
from services.datetime_serialization import serialize_datetime_iso
from services.db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from services.error_messages import ERROR_CHAT_ROOM_NOT_FOUND, ERROR_SHARED_LINK_NOT_FOUND
from services.generative_ui import decode_message_parts, encode_message_parts

UNIQUE_VIOLATION_PGCODE = "23505"
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
SHARED_TOKEN_MAX_COLLISION_RETRIES = 5


class ChatRepository:
    """chat_rooms/chat_history の永続化をまとめる境界。

    テストでは connection_getter や sleep を差し替え、DB 再試行や一意制約衝突を
    実 DB なしで検証できるようにしている。
    """

    def __init__(
        self,
        *,
        connection_getter: Callable[[], Any] = get_db_connection,
        retryable_error_checker: Callable[[BaseException], bool] = is_retryable_db_error,
        rollback: Callable[[Any], bool] = rollback_connection,
        sleep: Callable[[float], Any] = time.sleep,
        token_generator: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self._connection_getter = connection_getter
        self._is_retryable_db_error = retryable_error_checker
        self._rollback = rollback
        self._sleep = sleep
        self._token_generator = token_generator

    def save_message(
        self,
        chat_room_id: str,
        message: str,
        sender: str,
        attached_file_names: list[str] | None = None,
        parent_id: int | None = None,
        message_parts: list[dict[str, Any]] | None = None,
        attached_file_contents: list[Any] | None = None,
    ) -> int | None:
        """Insert a message and make it the active branch tip.

        When ``parent_id`` is given, the new message becomes a child of that
        message and the parent's ``active_child_id`` is repointed at it (creating
        or switching a branch). When ``parent_id`` is ``None`` the new message
        becomes the active root of the room.
        """
        file_names_json = json.dumps(attached_file_names, ensure_ascii=False) if attached_file_names else None
        message_parts_json = encode_message_parts(message_parts)
        attached_file_contents_json = encode_attached_files_for_storage(attached_file_contents)
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    query = """
                        INSERT INTO chat_history (
                            chat_room_id,
                            message,
                            sender,
                            attached_file_names,
                            parent_id,
                            message_parts,
                            attached_file_contents
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """
                    cursor.execute(
                        query,
                        (
                            chat_room_id,
                            message,
                            sender,
                            file_names_json,
                            parent_id,
                            message_parts_json,
                            attached_file_contents_json,
                        ),
                    )
                    row = cursor.fetchone()
                    new_id = row[0] if row else None
                    if new_id is not None:
                        # chat_history は木構造で全バージョンを保持し、active_root_id /
                        # active_child_id だけを動かして現在表示中の枝を切り替える。
                        if parent_id is None:
                            cursor.execute(
                                "UPDATE chat_rooms SET active_root_id = %s WHERE id = %s",
                                (new_id, chat_room_id),
                            )
                        else:
                            cursor.execute(
                                "UPDATE chat_history SET active_child_id = %s WHERE id = %s AND chat_room_id = %s",
                                (new_id, parent_id, chat_room_id),
                            )
                    conn.commit()
                    return new_id
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()

        raise RuntimeError("Failed to save chat message after retry attempts.")

    def create_room(self, room_id: str, user_id: int, title: str, mode: str = "normal") -> None:
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    query = "INSERT INTO chat_rooms (id, user_id, title, mode) VALUES (%s, %s, %s, %s)"
                    cursor.execute(query, (room_id, user_id, title, mode))
                    conn.commit()
                    return
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()

        raise RuntimeError("Failed to create chat room after retry attempts.")

    def delete_room_if_no_assistant_messages(self, room_id: str, user_id: int) -> bool:
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "SELECT user_id FROM chat_rooms WHERE id = %s",
                        (room_id,),
                    )
                    row = cursor.fetchone()
                    if not row or row[0] != user_id:
                        return False

                    cursor.execute(
                        """
                        SELECT 1
                          FROM chat_history
                         WHERE chat_room_id = %s
                           AND sender = 'assistant'
                         LIMIT 1
                        """,
                        (room_id,),
                    )
                    if cursor.fetchone():
                        return False

                    # assistant 応答がまだない部屋だけを消す。生成失敗・quota 超過時の掃除用で、
                    # 会話済みの部屋を誤って消さないためのガード。
                    cursor.execute("DELETE FROM chat_history WHERE chat_room_id = %s", (room_id,))
                    cursor.execute(
                        "DELETE FROM chat_rooms WHERE id = %s AND user_id = %s",
                        (room_id, user_id),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()

        raise RuntimeError("Failed to delete chat room without assistant messages after retry attempts.")

    def delete_messages_from_trailing_user_count(self, chat_room_id: str, trailing_user_count: int) -> bool:
        """Delete messages starting from the user message that has `trailing_user_count` user
        messages after it (counting from the newest).  trailing_user_count=0 targets the last
        user message; trailing_user_count=1 targets the second-to-last, etc.

        Returns True if any rows were deleted.
        """
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "SELECT id FROM chat_history WHERE chat_room_id = %s AND sender = 'user' ORDER BY id ASC",
                        (chat_room_id,),
                    )
                    user_ids = [row[0] for row in cursor.fetchall()]

                    if len(user_ids) <= trailing_user_count:
                        return False

                    target_id = user_ids[len(user_ids) - 1 - trailing_user_count]
                    cursor.execute(
                        "DELETE FROM chat_history WHERE chat_room_id = %s AND id >= %s",
                        (chat_room_id, target_id),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()
        return False

    def delete_last_assistant_message(self, chat_room_id: str) -> bool:
        """Delete the last assistant message (and any messages after it) from a chat room."""
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        """
                        SELECT id FROM chat_history
                        WHERE chat_room_id = %s AND sender = 'assistant'
                        ORDER BY id DESC LIMIT 1
                        """,
                        (chat_room_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return False
                    last_id = row[0]
                    cursor.execute(
                        "DELETE FROM chat_history WHERE chat_room_id = %s AND id >= %s",
                        (chat_room_id, last_id),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()
        return False

    def rename_room(self, room_id: str, new_title: str) -> None:
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    query = "UPDATE chat_rooms SET title = %s WHERE id = %s"
                    cursor.execute(query, (new_title, room_id))
                    conn.commit()
                    return
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()

        raise RuntimeError("Failed to rename chat room after retry attempts.")

    def rename_room_if_current_title_in(
        self,
        room_id: str,
        new_title: str,
        allowed_current_titles: list[str],
    ) -> bool:
        # 自動タイトル生成は初期タイトルのままの部屋だけを更新する。
        # ユーザーが手動で改名済みなら WHERE title IN (...) が外れて上書きしない。
        normalized_titles = [title for title in dict.fromkeys(allowed_current_titles) if title]
        if not normalized_titles:
            return False

        title_placeholders = ", ".join(["%s"] * len(normalized_titles))
        query = f"""
            UPDATE chat_rooms
               SET title = %s
             WHERE id = %s
               AND title IN ({title_placeholders})
        """
        params = (new_title, room_id, *normalized_titles)

        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(query, params)
                    updated = cursor.rowcount > 0
                    conn.commit()
                    return updated
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()

        raise RuntimeError("Failed to conditionally rename chat room after retry attempts.")

    # ----- Branching helpers -------------------------------------------------

    def _load_room_tree(
        self, cursor: Any, chat_room_id: str
    ) -> tuple[dict[int, dict[str, Any]], int | None]:
        """Load every message of a room plus the room's active root pointer."""
        cursor.execute(
            """
            SELECT id,
                   message,
                   sender,
                   parent_id,
                   active_child_id,
                   timestamp,
                   attached_file_names,
                   message_parts,
                   attached_file_contents
              FROM chat_history
             WHERE chat_room_id = %s
             ORDER BY id ASC
            """,
            (chat_room_id,),
        )
        nodes: dict[int, dict[str, Any]] = {}
        for (
            message_id,
            message,
            sender,
            parent_id,
            active_child_id,
            ts,
            file_names_json,
            message_parts_json,
            attached_file_contents_json,
        ) in cursor.fetchall():
            nodes[message_id] = {
                "id": message_id,
                "message": message,
                "sender": sender,
                "parent_id": parent_id,
                "active_child_id": active_child_id,
                "timestamp": ts,
                "attached_file_names": file_names_json,
                "message_parts": message_parts_json,
                "attached_file_contents": attached_file_contents_json,
            }

        cursor.execute("SELECT active_root_id FROM chat_rooms WHERE id = %s", (chat_room_id,))
        room_row = cursor.fetchone()
        active_root_id = room_row[0] if room_row else None
        return nodes, active_root_id

    @staticmethod
    def _children_by_parent(nodes: dict[int, dict[str, Any]]) -> dict[int | None, list[int]]:
        children: dict[int | None, list[int]] = defaultdict(list)
        for node in nodes.values():
            children[node["parent_id"]].append(node["id"])
        for sibling_ids in children.values():
            sibling_ids.sort()
        return children

    def _walk_active_path(
        self,
        nodes: dict[int, dict[str, Any]],
        active_root_id: int | None,
        children: dict[int | None, list[int]],
    ) -> list[dict[str, Any]]:
        """Follow active_child pointers from the active root down to a leaf."""
        root_siblings = children.get(None, [])
        current = active_root_id if active_root_id in nodes else (root_siblings[-1] if root_siblings else None)

        path: list[dict[str, Any]] = []
        visited: set[int] = set()
        # 壊れた active_child_id や循環があっても履歴取得を止めない。
        # ポインタが欠けた場合は最後に作られた子を暫定的な active path として返す。
        while current is not None and current in nodes and current not in visited:
            visited.add(current)
            node = nodes[current]
            path.append(node)
            nxt = node["active_child_id"]
            if nxt is None or nxt not in nodes:
                child_ids = children.get(current, [])
                nxt = child_ids[-1] if child_ids else None
            current = nxt
        return path

    def _decode_file_names(self, file_names_json: Any) -> list[str] | None:
        if not file_names_json:
            return None
        try:
            parsed = json.loads(file_names_json)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(parsed, list):
            names = [str(n) for n in parsed if isinstance(n, str)]
            return names or None
        return None

    def _serialize_path_node(
        self,
        node: dict[str, Any],
        children: dict[int | None, list[int]],
        *,
        include_files: bool = True,
        include_attachment_contents: bool = False,
    ) -> dict[str, Any]:
        sibling_ids = children.get(node["parent_id"], [])
        try:
            version_index = sibling_ids.index(node["id"]) + 1
        except ValueError:
            version_index = 1
        entry: dict[str, Any] = {
            "id": node["id"],
            "message": node["message"],
            "sender": node["sender"],
            "timestamp": serialize_datetime_iso(node["timestamp"]),
            "version_index": version_index,
            "version_count": len(sibling_ids) or 1,
            "sibling_ids": list(sibling_ids),
        }
        if include_files:
            file_names = self._decode_file_names(node["attached_file_names"])
            if file_names:
                entry["attached_file_names"] = file_names
        message_parts = decode_message_parts(node.get("message_parts"))
        if message_parts:
            entry["message_parts"] = message_parts
        if include_attachment_contents:
            attached_file_contents = decode_attached_files_from_storage(
                node.get("attached_file_contents")
            )
            if attached_file_contents:
                entry["attached_file_contents"] = [
                    {"name": attached_file.name, "content": attached_file.content}
                    for attached_file in attached_file_contents
                ]
        return entry

    def get_active_path(
        self,
        chat_room_id: str,
        *,
        include_attachment_contents: bool = False,
    ) -> list[dict[str, Any]]:
        """Return the active branch as serialized messages with version metadata."""
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                nodes, active_root_id = self._load_room_tree(cursor, chat_room_id)
                children = self._children_by_parent(nodes)
                path = self._walk_active_path(nodes, active_root_id, children)
                return [
                    self._serialize_path_node(
                        node,
                        children,
                        include_attachment_contents=include_attachment_contents,
                    )
                    for node in path
                ]
            finally:
                cursor.close()

    def get_active_leaf_id(self, chat_room_id: str) -> int | None:
        """Return the id of the last message on the active branch (None if empty)."""
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                nodes, active_root_id = self._load_room_tree(cursor, chat_room_id)
                children = self._children_by_parent(nodes)
                path = self._walk_active_path(nodes, active_root_id, children)
                return path[-1]["id"] if path else None
            finally:
                cursor.close()

    def switch_branch(self, chat_room_id: str, target_id: int) -> list[dict[str, Any]]:
        """Make ``target_id`` the active sibling and return the new active path."""
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "SELECT parent_id FROM chat_history WHERE id = %s AND chat_room_id = %s",
                        (target_id, chat_room_id),
                    )
                    row = cursor.fetchone()
                    if not row:
                        raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
                    parent_id = row[0]
                    if parent_id is None:
                        cursor.execute(
                            "UPDATE chat_rooms SET active_root_id = %s WHERE id = %s",
                            (target_id, chat_room_id),
                        )
                    else:
                        cursor.execute(
                            "UPDATE chat_history SET active_child_id = %s WHERE id = %s AND chat_room_id = %s",
                            (target_id, parent_id, chat_room_id),
                        )
                    conn.commit()

                    nodes, active_root_id = self._load_room_tree(cursor, chat_room_id)
                    children = self._children_by_parent(nodes)
                    path = self._walk_active_path(nodes, active_root_id, children)
                    return [self._serialize_path_node(node, children) for node in path]
                except (ResourceNotFoundError, ForbiddenOperationError):
                    raise
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()
        raise RuntimeError("Failed to switch chat branch after retry attempts.")

    def get_room_messages_for_llm(self, chat_room_id: str) -> list[dict[str, str]]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                nodes, active_root_id = self._load_room_tree(cursor, chat_room_id)
                children = self._children_by_parent(nodes)
                path = self._walk_active_path(nodes, active_root_id, children)
                messages = []
                for node in path:
                    role = "user" if node["sender"] == "user" else "assistant"
                    messages.append({"role": role, "content": node["message"]})
                return messages
            finally:
                cursor.close()

    def validate_room_owner(
        self,
        room_id: str,
        user_id: int,
        forbidden_message: str,
    ) -> str | None:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                check_q = "SELECT user_id, COALESCE(mode, 'normal') FROM chat_rooms WHERE id = %s"
                cursor.execute(check_q, (room_id,))
                result = cursor.fetchone()
                if not result:
                    raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
                if result[0] != user_id:
                    raise ForbiddenOperationError(forbidden_message)
                if len(result) < 2:
                    return None
                return str(result[1] or "normal")
            finally:
                cursor.close()

    def create_or_get_shared_chat_token(self, room_id: str, user_id: int) -> str:
        for _ in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
            token = self._token_generator(18)
            collision_detected = False

            for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
                with self._connection_getter() as conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute(
                            "SELECT user_id FROM chat_rooms WHERE id = %s",
                            (room_id,),
                        )
                        room_owner = cursor.fetchone()
                        if not room_owner:
                            raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
                        if room_owner[0] != user_id:
                            raise ForbiddenOperationError("他ユーザーのチャットルームは共有できません")

                        cursor.execute(
                            """
                            INSERT INTO shared_chat_rooms (chat_room_id, share_token)
                            VALUES (%s, %s)
                            ON CONFLICT (chat_room_id)
                            DO UPDATE SET chat_room_id = EXCLUDED.chat_room_id
                            RETURNING share_token
                            """,
                            (room_id, token),
                        )
                        row = cursor.fetchone()
                        conn.commit()
                        return row[0] if row else token
                    except (ResourceNotFoundError, ForbiddenOperationError):
                        raise
                    except Exception as exc:
                        self._rollback(conn)
                        if getattr(exc, "pgcode", None) == UNIQUE_VIOLATION_PGCODE:
                            collision_detected = True
                            break
                        if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                            self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                            continue
                        raise
                    finally:
                        cursor.close()

            if collision_detected:
                continue

        raise RuntimeError("Failed to create shared chat token after collision retries.")

    def get_shared_chat_room_payload(self, token: str) -> dict[str, Any]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT cr.id, cr.title, cr.created_at
                      FROM shared_chat_rooms scr
                      JOIN chat_rooms cr ON cr.id = scr.chat_room_id
                     WHERE scr.share_token = %s
                     LIMIT 1
                    """,
                    (token,),
                )
                room_row = cursor.fetchone()
                if not room_row:
                    raise ResourceNotFoundError(ERROR_SHARED_LINK_NOT_FOUND)

                room_id, title, created_at = room_row
                nodes, active_root_id = self._load_room_tree(cursor, room_id)
                children = self._children_by_parent(nodes)
                path = self._walk_active_path(nodes, active_root_id, children)
                messages = []
                for node in path:
                    entry = {
                        "message": node["message"],
                        "sender": node["sender"],
                        "timestamp": serialize_datetime_iso(node["timestamp"]),
                    }
                    message_parts = decode_message_parts(node.get("message_parts"))
                    if message_parts:
                        entry["message_parts"] = message_parts
                    messages.append(entry)

                return {
                    "room": {
                        "id": room_id,
                        "title": title,
                        "created_at": serialize_datetime_iso(created_at),
                    },
                    "messages": messages,
                }
            finally:
                cursor.close()

    def get_task_prompt_data(self, task: str, user_id: int | None) -> dict[str, Any] | None:
        with self._connection_getter() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                if user_id:
                    query = """
                        SELECT name,
                               prompt_template,
                               response_rules,
                               output_skeleton,
                               input_examples,
                               output_examples
                         FROM task_with_examples
                         WHERE name = %s
                           AND deleted_at IS NULL
                           AND (user_id = %s OR user_id IS NULL)
                         ORDER BY CASE WHEN user_id = %s THEN 0 ELSE 1 END, id
                         LIMIT 1
                    """
                    cursor.execute(query, (task, user_id, user_id))
                else:
                    query = """
                        SELECT name,
                               prompt_template,
                               response_rules,
                               output_skeleton,
                               input_examples,
                               output_examples
                         FROM task_with_examples
                         WHERE name = %s
                           AND deleted_at IS NULL
                           AND user_id IS NULL
                         ORDER BY id
                         LIMIT 1
                    """
                    cursor.execute(query, (task,))
                return cursor.fetchone()
            finally:
                cursor.close()

    def fetch_chat_history_page(
        self,
        chat_room_id: str,
        limit: int,
        before_message_id: int | None = None,
    ) -> dict[str, Any]:
        # History renders the active branch (not every stored message), paginated
        # newest-first by walking back along the active path.
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                nodes, active_root_id = self._load_room_tree(cursor, chat_room_id)
                children = self._children_by_parent(nodes)
                path = self._walk_active_path(nodes, active_root_id, children)

                if before_message_id is not None:
                    path = [node for node in path if node["id"] < before_message_id]

                has_more = len(path) > limit
                page_nodes = path[-limit:] if limit > 0 else []

                messages = [
                    self._serialize_path_node(node, children) for node in page_nodes
                ]
                next_before_id = messages[0]["id"] if has_more and messages else None
                return {
                    "messages": messages,
                    "pagination": {
                        "limit": limit,
                        "has_more": has_more,
                        "next_before_id": next_before_id,
                    },
                }
            finally:
                cursor.close()
