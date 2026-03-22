import logging
from typing import Any

from fastapi import Request

from services.async_utils import run_blocking
from services.db import get_db_connection
from services.default_tasks import default_task_payloads
from services.request_models import (
    AddTaskRequest,
    DeleteTaskRequest,
    EditTaskRequest,
    UpdateTasksOrderRequest,
)
from services.web import (
    jsonify,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from . import chat_bp

logger = logging.getLogger(__name__)


def _fetch_tasks_from_db(user_id: int | None) -> list[dict[str, Any]]:
    # ログイン時はユーザー個別タスク、未ログイン時は共通タスクを取得する
    # Fetch user-specific tasks when logged in, otherwise shared default tasks.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if user_id:
            cursor.execute(
                """
              SELECT name,
                     prompt_template,
                     response_rules,
                     output_skeleton,
                     input_examples,
                     output_examples,
                     FALSE AS is_default
                FROM task_with_examples
               WHERE user_id = %s
                 AND deleted_at IS NULL
               ORDER BY COALESCE(display_order, 99999),
                        id
            """,
                (user_id,),
            )
        else:
            cursor.execute(
                """
              SELECT name,
                     prompt_template,
                     response_rules,
                     output_skeleton,
                     input_examples,
                     output_examples,
                     TRUE AS is_default
                FROM task_with_examples
               WHERE user_id IS NULL
                 AND deleted_at IS NULL
               ORDER BY COALESCE(display_order, 99999), id
            """
            )

        return cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _update_tasks_order_for_user(user_id: int, new_order: list[str]) -> None:
    # 受け取った順序配列で display_order を更新する
    # Update display_order according to the provided order list.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        for index, task_name in enumerate(new_order):
            cursor.execute(
                """
                UPDATE task_with_examples
                   SET display_order=%s
                 WHERE name=%s AND user_id=%s
                   AND deleted_at IS NULL
            """,
                (index, task_name, user_id),
            )
        conn.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _delete_task_for_user(user_id: int, task_name: str) -> None:
    # ユーザー所有タスクを1件削除する
    # Delete a single user-owned task.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            UPDATE task_with_examples
               SET deleted_at = CURRENT_TIMESTAMP
             WHERE name = %s
               AND user_id = %s
               AND deleted_at IS NULL
        """
        cursor.execute(query, (task_name, user_id))
        conn.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _edit_task_for_user(
    user_id: int,
    old_task: str,
    new_task: str,
    prompt_template: str | None,
    response_rules: str | None,
    output_skeleton: str | None,
    input_examples: str | None,
    output_examples: str | None,
) -> bool:
    # 対象タスク存在確認後に内容を更新し、更新可否を返す
    # Update task after existence check and return whether update succeeded.
    conn = None
    sel_cursor = None
    upd_cursor = None
    try:
        conn = get_db_connection()
        sel_cursor = conn.cursor()
        sel_cursor.execute(
            """
            SELECT 1
              FROM task_with_examples
             WHERE name = %s
               AND user_id = %s
               AND deleted_at IS NULL
            """,
            (old_task, user_id),
        )
        exists = sel_cursor.fetchone()
        if not exists:
            return False

        upd_cursor = conn.cursor()
        upd_cursor.execute(
            """
            UPDATE task_with_examples
               SET name            = %s,
                   prompt_template = %s,
                   response_rules  = %s,
                   output_skeleton = %s,
                   input_examples  = %s,
                   output_examples = %s
             WHERE name = %s
               AND user_id = %s
               AND deleted_at IS NULL
            """,
            (
                new_task,
                prompt_template,
                response_rules,
                output_skeleton,
                input_examples,
                output_examples,
                old_task,
                user_id,
            ),
        )
        conn.commit()
        return True
    finally:
        if sel_cursor is not None:
            sel_cursor.close()
        if upd_cursor is not None:
            upd_cursor.close()
        if conn is not None:
            conn.close()


def _add_task_for_user(
    user_id: int,
    title: str,
    prompt_content: str,
    response_rules: str,
    output_skeleton: str,
    input_examples: str,
    output_examples: str,
) -> None:
    # ユーザー専用タスクを新規追加する
    # Insert a new user-owned task.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO task_with_examples
                  (
                      name,
                      prompt_template,
                      response_rules,
                      output_skeleton,
                      input_examples,
                      output_examples,
                      user_id
                  )
            VALUES (%s,   %s,               %s,             %s,             %s,             %s,             %s)
        """
        cursor.execute(
            query,
            (
                title,
                prompt_content,
                response_rules,
                output_skeleton,
                input_examples,
                output_examples,
                user_id,
            ),
        )
        conn.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@chat_bp.get("/api/tasks", name="chat.get_tasks")
async def get_tasks(request: Request):
    """
    ログインしている場合:
        ・自分のタスクのみ返す（共通タスクは登録時に複製されているため不要）
    未ログインの場合:
        ・共通タスク (user_id IS NULL) のみ返す
    """
    try:
        session = request.session
        # user_id が None や空文字の場合は未ログインとして扱う
        # Treat None/empty user_id as guest state.
        user_id = session.get("user_id")
        if not user_id:
            user_id = None

        tasks = []
        try:
            tasks = await run_blocking(_fetch_tasks_from_db, user_id)

        except Exception:
            logger.exception("Database error while loading tasks.")
            # ログインユーザーの場合、DBエラーはそのままエラーとして扱う（または空リスト？）
            # For logged-in users, surface DB failures as server errors.
            # ここでは安全のためエラーをログに出しつつ、
            # We log the exception and keep fallback path for guests only.
            # もし未ログインならデフォルトタスクを返すようにフローを継続する
            # Continue to guest fallback flow when not authenticated.
            if user_id:
                # ユーザーがいるのにDBエラーなら500にする（frontendでハンドリングされる）
                # Raise for authenticated users so frontend receives 500.
                raise
            # 未ログインならDBエラーでも続行（tasks=[] のまま）
            # For guests, continue and allow default-task fallback.

        # 未ログイン かつ タスクが取得できていない場合はデフォルトタスクを使用
        # Use bundled default tasks when guest tasks could not be loaded.
        if not user_id and not tasks:
            tasks = default_task_payloads()

        return jsonify({"tasks": tasks})

    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to load tasks.",
        )


# タスクカード並び替え
# Reorder task cards for authenticated users.
@chat_bp.post("/api/update_tasks_order", name="chat.update_tasks_order")
async def update_tasks_order(request: Request):
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify({"error": "ログインが必要です"}, status_code=403)
    payload, validation_error = validate_payload_model(
        data,
        UpdateTasksOrderRequest,
        error_message="order must be a list",
    )
    if validation_error is not None:
        return validation_error

    new_order = payload.order
    try:
        await run_blocking(_update_tasks_order_for_user, user_id, new_order)
        return jsonify({"message": "Order updated"}, status_code=200)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to update task order.",
        )


@chat_bp.post("/api/delete_task", name="chat.delete_task")
async def delete_task(request: Request):
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify({"error": "ログインが必要です"}, status_code=403)
    payload, validation_error = validate_payload_model(
        data,
        DeleteTaskRequest,
        error_message="task is required",
    )
    if validation_error is not None:
        return validation_error

    task_name = payload.task
    try:
        await run_blocking(_delete_task_for_user, user_id, task_name)
        return jsonify({"message": "Task deleted"}, status_code=200)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to delete task.",
        )


@chat_bp.post("/api/edit_task", name="chat.edit_task")
async def edit_task(request: Request):
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify({"error": "ログインが必要です"}, status_code=403)

    payload, validation_error = validate_payload_model(
        data,
        EditTaskRequest,
        error_message="old_task と new_task は必須です",
    )
    if validation_error is not None:
        return validation_error

    try:
        updated = await run_blocking(
            _edit_task_for_user,
            user_id,
            payload.old_task,
            payload.new_task,
            payload.prompt_template,
            payload.response_rules,
            payload.output_skeleton,
            payload.input_examples,
            payload.output_examples,
        )
        if not updated:
            return jsonify({"error": "他ユーザーのタスクは編集できません"}, status_code=403)

        return jsonify({"message": "Task updated"}, status_code=200)

    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to edit task.",
        )


@chat_bp.post("/api/add_task", name="chat.add_task")
async def add_task(request: Request):
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify({"error": "ログインが必要です"}, status_code=403)

    payload, validation_error = validate_payload_model(
        data,
        AddTaskRequest,
        error_message="タイトルとプロンプト内容は必須です。",
    )
    if validation_error is not None:
        return validation_error

    try:
        await run_blocking(
            _add_task_for_user,
            user_id,
            payload.title,
            payload.prompt_content,
            payload.response_rules,
            payload.output_skeleton,
            payload.input_examples,
            payload.output_examples,
        )
        return jsonify({"message": "タスクが追加されました"}, status_code=201)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to add task.",
        )
