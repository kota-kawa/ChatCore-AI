import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, Request
from starlette.responses import StreamingResponse

from services.auth_limits import (
    AuthLimitService,
    consume_rate_limit,
    get_auth_limit_service,
    get_request_client_ip,
)
from services.api_errors import DEFAULT_RETRY_AFTER_SECONDS, parse_retry_after_seconds
from services.async_utils import run_blocking
from services.agent_capabilities import build_capability_context
from services.db import get_db_connection
from services.default_tasks import default_task_payloads
from services.llm import (
    GPT_OSS_120B_MODEL,
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmRateLimitError,
    LlmServiceError,
    get_llm_response,
    is_retryable_llm_error,
)
from services.llm_daily_limit import (
    LlmDailyLimitService,
    consume_llm_daily_quota,
    get_seconds_until_daily_reset,
    get_llm_daily_limit_service,
)
from services.code_search import search_codebase
from services.intent_classifier import classify_intent
from services.manual_rag import search_manual
from services.page_actions import build_action_messages, parse_action_response
from services.page_context import get_page_context
from services.prompt_assist import create_prompt_assist_payload
from services.request_models import (
    AddTaskRequest,
    AiAgentRequest,
    DeleteTaskRequest,
    EditTaskRequest,
    PromptAssistRequest,
    UpdateTasksOrderRequest,
)
from services.web import (
    jsonify,
    jsonify_rate_limited,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from . import chat_bp, get_session_id

logger = logging.getLogger(__name__)
PROMPT_ASSIST_RATE_WINDOW_SECONDS = 300
PROMPT_ASSIST_PER_IP_LIMIT = 20
PROMPT_ASSIST_PER_USER_LIMIT = 30
AI_AGENT_RATE_WINDOW_SECONDS = 300
AI_AGENT_PER_IP_LIMIT = 30
AI_AGENT_PER_ACTOR_LIMIT = 40

AI_AGENT_SYSTEM_PROMPT = """
あなたは ChatCore の全ページ共通AIエージェントです。
ユーザーの作業を短く、実用的に支援してください。

応答ルール:
- 日本語で自然に答える。
- まず結論や次の一手を示す。
- 回答は、ユーザーが一目で要点を把握できるように Markdown で整形する。
- まず最初に、結論や直接の答えを 1〜2 文で示す。
- 短い質問には短く答え、過剰な見出しや表は使わない。
- 手順、選択肢、注意点、要因の列挙には Markdown の箇条書きを使う。
- 2 項目以上を比較する場合は、比較軸が明確なときに Markdown の表を使う。
- 重要な語句、結論、注意点だけを太字にする。太字を多用しない。
- コード、コマンド、JSON、SQL、設定例は、見やすさが上がる場合は言語指定付きコードブロックで示す。
- そのまま貼り付けて使う文案やテンプレートは、説明部分と分けてコードブロックで示す。
- 長すぎる前置きやAIらしい定型句は避ける。
- 装飾目的だけの Markdown は使わない。
- 画面操作やプロンプト作成の相談では、具体的な文案や改善案を出す。
""".strip()


def _resolve_auth_limit_service(
    request: Request,
    service: AuthLimitService | None,
) -> AuthLimitService:
    if isinstance(service, AuthLimitService):
        return service
    return get_auth_limit_service(request)


def _resolve_llm_daily_limit_service(
    request: Request,
    service: LlmDailyLimitService | None,
) -> LlmDailyLimitService:
    if isinstance(service, LlmDailyLimitService):
        return service
    return get_llm_daily_limit_service(request)


def _consume_prompt_assist_limits(
    request: Request,
    user_id: int | str,
    *,
    auth_limit_service: AuthLimitService | None = None,
) -> tuple[bool, str | None]:
    client_ip = get_request_client_ip(request)
    allowed, _, retry_after = consume_rate_limit(
        "prompt_assist:ip",
        client_ip,
        limit=PROMPT_ASSIST_PER_IP_LIMIT,
        window_seconds=PROMPT_ASSIST_RATE_WINDOW_SECONDS,
        service=auth_limit_service,
    )
    if not allowed:
        return (
            False,
            (
                "AI補助の試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )

    allowed, _, retry_after = consume_rate_limit(
        "prompt_assist:user",
        str(user_id),
        limit=PROMPT_ASSIST_PER_USER_LIMIT,
        window_seconds=PROMPT_ASSIST_RATE_WINDOW_SECONDS,
        service=auth_limit_service,
    )
    if not allowed:
        return (
            False,
            (
                "AI補助の試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )
    return True, None


def _consume_ai_agent_limits(
    request: Request,
    actor_key: str,
    *,
    auth_limit_service: AuthLimitService | None = None,
) -> tuple[bool, str | None]:
    client_ip = get_request_client_ip(request)
    allowed, _, retry_after = consume_rate_limit(
        "ai_agent:ip",
        client_ip,
        limit=AI_AGENT_PER_IP_LIMIT,
        window_seconds=AI_AGENT_RATE_WINDOW_SECONDS,
        service=auth_limit_service,
    )
    if not allowed:
        return (
            False,
            (
                "AIエージェントの試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )

    allowed, _, retry_after = consume_rate_limit(
        "ai_agent:actor",
        actor_key,
        limit=AI_AGENT_PER_ACTOR_LIMIT,
        window_seconds=AI_AGENT_RATE_WINDOW_SECONDS,
        service=auth_limit_service,
    )
    if not allowed:
        return (
            False,
            (
                "AIエージェントの試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )
    return True, None


def _ai_agent_sse(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


def _build_ai_agent_messages(
    payload: AiAgentRequest,
    rag_context: str = "",
) -> list[dict[str, str]]:
    recent_messages = payload.messages[-12:]
    system_content = f"{AI_AGENT_SYSTEM_PROMPT}\n\n{build_capability_context(payload.current_page or '')}"
    if rag_context:
        system_content = f"{system_content}\n\n{rag_context}"
    conversation_messages = [{"role": "system", "content": system_content}]
    conversation_messages.extend(
        {"role": message.role, "content": message.content}
        for message in recent_messages
    )
    return conversation_messages


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


@chat_bp.post("/api/prompt-assist", name="chat.prompt_assist")
async def prompt_assist(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    resolved_llm_daily_limit_service = _resolve_llm_daily_limit_service(
        request,
        llm_daily_limit_service,
    )
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify({"error": "ログインが必要です"}, status_code=403)

    payload, validation_error = validate_payload_model(
        data,
        PromptAssistRequest,
        error_message="AI補助リクエストが不正です。",
    )
    if validation_error is not None:
        return validation_error

    can_access, limit_message = await run_blocking(
        _consume_prompt_assist_limits,
        request,
        user_id,
        auth_limit_service=resolved_auth_limit_service,
    )
    if not can_access:
        return jsonify_rate_limited(
            limit_message or "試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=parse_retry_after_seconds(
                limit_message,
                default=DEFAULT_RETRY_AFTER_SECONDS,
            ),
        )

    can_access_llm, _, daily_limit = await run_blocking(
        consume_llm_daily_quota,
        service=resolved_llm_daily_limit_service,
    )
    if not can_access_llm:
        return jsonify_rate_limited(
            (
                f"本日のLLM API利用上限（全ユーザー合計 {daily_limit} 回）に達しました。"
                "日付が変わってから再度お試しください。"
            ),
            retry_after=get_seconds_until_daily_reset(),
        )

    try:
        dump_fields = getattr(payload.fields, "model_dump", None)
        result = await run_blocking(
            create_prompt_assist_payload,
            payload.target,
            payload.action,
            dump_fields() if callable(dump_fields) else payload.fields.dict(),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}, status_code=400)
    except LlmRateLimitError as exc:
        return jsonify_rate_limited(
            "AI補助の呼び出しが混み合っています。時間をおいて再試行してください。",
            retry_after=(
                exc.retry_after_seconds
                if exc.retry_after_seconds is not None
                else DEFAULT_RETRY_AFTER_SECONDS
            ),
        )
    except LlmAuthenticationError:
        logger.exception("Prompt assist failed due to LLM authentication/configuration issue.")
        return jsonify(
            {"error": "AI補助の設定エラーが発生しました。管理者に連絡してください。"},
            status_code=502,
        )
    except LlmServiceError as exc:
        logger.exception("Failed to generate prompt assist suggestion.")
        retryable = is_retryable_llm_error(exc)
        return jsonify(
            {
                "error": "AI補助の取得に失敗しました。時間をおいて再試行してください。",
                "retryable": retryable,
            },
            status_code=502,
        )
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to handle prompt assist request.",
        )


@chat_bp.post("/api/ai-agent", name="chat.ai_agent")
async def ai_agent(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    resolved_llm_daily_limit_service = _resolve_llm_daily_limit_service(
        request,
        llm_daily_limit_service,
    )
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        AiAgentRequest,
        error_message="AIエージェントリクエストが不正です。",
    )
    if validation_error is not None:
        return validation_error

    user_id = request.session.get("user_id")
    actor_key = f"user:{user_id}" if user_id else f"guest:{get_session_id(request.session)}"
    can_access, limit_message = await run_blocking(
        _consume_ai_agent_limits,
        request,
        actor_key,
        auth_limit_service=resolved_auth_limit_service,
    )
    if not can_access:
        return jsonify_rate_limited(
            limit_message or "試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=parse_retry_after_seconds(
                limit_message,
                default=DEFAULT_RETRY_AFTER_SECONDS,
            ),
        )

    can_access_llm, _, daily_limit = await run_blocking(
        consume_llm_daily_quota,
        service=resolved_llm_daily_limit_service,
    )
    if not can_access_llm:
        return jsonify_rate_limited(
            (
                f"本日のLLM API利用上限（全ユーザー合計 {daily_limit} 回）に達しました。"
                "日付が変わってから再度お試しください。"
            ),
            retry_after=get_seconds_until_daily_reset(),
        )

    async def _stream() -> AsyncIterator[bytes]:
        try:
            last_user_message = next(
                (m.content for m in reversed(payload.messages) if m.role == "user"),
                "",
            )
            current_page = payload.current_page or ""
            rag_context = ""
            dom_context = ""
            if payload.current_dom:
                dom_context = f"【現在ブラウザで見えている操作可能要素】\n{payload.current_dom}"

            yield _ai_agent_sse("progress", {"message": "依頼内容を確認中..."})
            intent = await run_blocking(classify_intent, last_user_message, current_page)

            if intent == "action":
                yield _ai_agent_sse("progress", {"message": "ページを解析中..."})
                page_ctx = await run_blocking(get_page_context, current_page)
                action_context = "\n\n".join(
                    part for part in (dom_context, page_ctx, build_capability_context(current_page)) if part
                )
                if action_context:
                    yield _ai_agent_sse("progress", {"message": "操作手順を生成中..."})
                    action_messages = build_action_messages(
                        action_context,
                        [{"role": m.role, "content": m.content} for m in payload.messages[-6:]],
                    )
                    response_text = await run_blocking(
                        get_llm_response, action_messages, GPT_OSS_120B_MODEL
                    )
                    action_plan = parse_action_response(response_text or "")
                    if action_plan:
                        yield _ai_agent_sse("action_plan", action_plan)
                        return
                    # セレクタ特定できず → ページコードをRAGとして通常応答にフォールスルー
                    rag_context = page_ctx

            elif intent == "page_info":
                yield _ai_agent_sse("progress", {"message": "現在のページを確認中..."})
                page_context = await run_blocking(get_page_context, current_page)
                rag_context = "\n\n".join(part for part in (dom_context, page_context) if part)
                if not rag_context:
                    yield _ai_agent_sse("progress", {"message": "マニュアルを検索中..."})
                    rag_context = await run_blocking(search_manual, last_user_message)

            elif intent == "search":
                yield _ai_agent_sse("progress", {"message": "マニュアルを検索中..."})
                rag_context = await run_blocking(search_manual, last_user_message)
                if not rag_context:
                    yield _ai_agent_sse("progress", {"message": "コードを探索中..."})
                    rag_context = await run_blocking(search_codebase, last_user_message)

            yield _ai_agent_sse("progress", {"message": "回答を生成中..."})
            response_text = await run_blocking(
                get_llm_response,
                _build_ai_agent_messages(payload, rag_context),
                GPT_OSS_120B_MODEL,
            )
            yield _ai_agent_sse("done", {"response": response_text or "", "model": GPT_OSS_120B_MODEL})

        except LlmRateLimitError as exc:
            retry = exc.retry_after_seconds if exc.retry_after_seconds is not None else DEFAULT_RETRY_AFTER_SECONDS
            yield _ai_agent_sse("error", {
                "message": "AIエージェントの呼び出しが混み合っています。時間をおいて再試行してください。",
                "retry_after": retry,
            })
        except (LlmAuthenticationError, LlmConfigurationError):
            logger.exception("AI agent failed due to LLM authentication/configuration issue.")
            yield _ai_agent_sse("error", {"message": "AIエージェントの設定エラーが発生しました。管理者に連絡してください。"})
        except LlmServiceError as exc:
            logger.exception("Failed to generate AI agent response.")
            yield _ai_agent_sse("error", {
                "message": "AIエージェントの応答生成に失敗しました。時間をおいて再試行してください。",
                "retryable": is_retryable_llm_error(exc),
            })
        except Exception:
            logger.exception("Failed to handle AI agent request.")
            yield _ai_agent_sse("error", {"message": "予期しないエラーが発生しました。"})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
