import re
import json
import html
import logging
from collections.abc import Iterator
from functools import partial
from datetime import date
from typing import Any

from fastapi import Request
from starlette.responses import StreamingResponse

from services.async_utils import run_blocking
from services.db import get_db_connection
from services.chat_service import (
    save_message_to_db,
    get_chat_room_messages,
    validate_room_owner,
)
from services.chat_generation import (
    ChatGenerationAlreadyRunningError,
    ChatGenerationJob,
    build_generation_key,
    get_generation_job,
    has_active_generation,
    start_generation_job,
)
from services.llm_daily_limit import consume_llm_daily_quota
from services.llm import (
    get_llm_response,
    GEMINI_DEFAULT_MODEL,
    LlmInvalidModelError,
    LlmServiceError,
    is_streaming_model,
)
from services.request_models import ChatMessageRequest
from services.web import (
    jsonify,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from . import (
    chat_bp,
    get_session_id,
    cleanup_ephemeral_chats,
    ephemeral_store,
)

logger = logging.getLogger(__name__)
CHAT_HISTORY_PAGE_SIZE_DEFAULT = 50
CHAT_HISTORY_PAGE_SIZE_MAX = 100

BASE_SYSTEM_PROMPT = """
あなたは、ユーザーをサポートする優秀なAIアシスタントです。
以下のガイドラインに従って、視覚的に分かりやすく、構造化された回答を生成してください。

1. **Markdownの積極的な活用**:
   - 回答の主要なセクションには「## 見出し」を使用してください。
   - 重要なポイントは **太字** で強調してください。
   - 情報を整理する際は、箇条書き（- または 1.）を使用してください。
   - 比較やデータを示す場合は、Markdownの表形式（Table）を活用してください。

2. **コードブロック**:
   - プログラミングコードやコマンド、設定ファイルの内容を出力する場合は、必ず適切な言語指定（例: ```python）を伴うコードブロックを使用してください。

3. **回答の構成**:
   - 最初に簡潔な結論や要約を述べ、その後に詳細な説明を続ける構成にしてください。
   - 長い回答になる場合は、適宜「### 小見出し」を使って論点を整理してください。

4. **タスク補助情報の扱い**:
   - システムから「タスク指示」「回答ルール」「出力テンプレート」「参考例」が追加されることがあります。
   - 参考例は構成や粒度の参考にとどめ、固有名詞・題材・結論をそのまま流用しないでください。
   - ユーザー情報が不足している場合は、決め打ちせず必要な確認事項を簡潔に質問してください。

回答は常に親切かつプロフェッショナルなトーンで、日本語で行ってください。
"""


def _sse_event(event: str, payload: dict[str, Any]) -> bytes:
    # SSE 形式で JSON ペイロードを1イベントとして返す
    # Encode one JSON payload as an SSE event.
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


def _iter_llm_stream_events(
    job: ChatGenerationJob,
) -> Iterator[bytes]:
    # 生成ジョブのイベント列を SSE として配信する
    # Convert background generation job events into SSE payloads.
    for event in job.iter_events():
        yield _sse_event(event.event, event.payload)


def _build_llm_stream_response(
    job: ChatGenerationJob,
) -> StreamingResponse:
    # バックグラウンド生成ジョブを StreamingResponse へ変換して SSE 配信する
    # Wrap the background generation job with StreamingResponse for SSE delivery.

    return StreamingResponse(
        _iter_llm_stream_events(job),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _parse_task_launch_message(message: str) -> dict[str, str] | None:
    # 初回タスク起動メッセージからタスク名と状況情報を抽出する
    # Extract task name and setup info from the initial task-launch payload.
    if not message:
        return None

    task_match = re.search(r"^【タスク】(?P<task>[^\n]+)", message, re.MULTILINE)
    if not task_match:
        return None

    setup_match = re.search(r"【状況・作業環境】(?P<setup>[\s\S]+)", message)
    setup_info = setup_match.group("setup").strip() if setup_match else ""
    return {
        "task": task_match.group("task").strip(),
        "setup_info": setup_info,
    }


def _fetch_prompt_data(task: str, user_id: int | None) -> dict[str, Any] | None:
    # タスク名に対応するプロンプト定義を取得する
    # Fetch prompt-template metadata for the selected task.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
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
                   AND user_id IS NULL
                 ORDER BY id
                 LIMIT 1
            """
            cursor.execute(query, (task,))
        return cursor.fetchone()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


async def _load_task_prompt_data(task: str, user_id: int | None) -> dict[str, Any] | None:
    # タスク補助情報の取得失敗ではチャット全体を止めず、ベースプロンプトのみで続行する
    # Do not fail the whole chat request when task metadata lookup fails.
    try:
        prompt_data = await run_blocking(_fetch_prompt_data, task, user_id)
    except Exception:
        logger.exception("Failed to load task prompt metadata for task launch: %s", task)
        return None

    if prompt_data is None:
        return None
    if not isinstance(prompt_data, dict):
        logger.warning("Ignoring malformed task prompt metadata for task launch: %s", task)
        return None
    return prompt_data


def _parse_example_list(examples: str | None) -> list[str]:
    # JSON配列または単一文字列の両方に対応して例を配列化する
    # Normalize example payloads into a list of strings.
    if not examples:
        return []

    examples = examples.strip()
    if not examples:
        return []

    if examples.startswith("["):
        try:
            loaded = json.loads(examples)
        except Exception:
            logger.warning("Failed to parse examples JSON; using raw text fallback.")
            return [examples]
        if isinstance(loaded, list):
            return [str(item).strip() for item in loaded if str(item).strip()]

    return [examples]


def _build_task_prompt(prompt_data: dict[str, Any]) -> str:
    # タスク定義から system 用の追加指示を組み立てる
    # Build a system prompt fragment from task metadata.
    sections: list[str] = []

    task_name = str(prompt_data.get("name", "")).strip()
    prompt_template = str(prompt_data.get("prompt_template", "")).strip()
    response_rules = str(prompt_data.get("response_rules", "")).strip()
    output_skeleton = str(prompt_data.get("output_skeleton", "")).strip()

    if task_name:
        sections.append(f"選択されたタスク: {task_name}")
    if prompt_template:
        sections.append(f"タスク指示:\n{prompt_template}")
    if response_rules:
        sections.append(f"回答ルール:\n{response_rules}")
    if output_skeleton:
        sections.append(f"出力テンプレート:\n{output_skeleton}")

    input_examples = _parse_example_list(prompt_data.get("input_examples"))
    output_examples = _parse_example_list(prompt_data.get("output_examples"))
    num_examples = min(len(input_examples), len(output_examples))
    if num_examples > 0:
        example_lines = [
            "参考例（構成や粒度だけを参考にし、語句や題材を流用しないこと）:"
        ]
        for i in range(num_examples):
            example_lines.append(f"入力例{i + 1}: {input_examples[i]}")
            example_lines.append(f"出力例{i + 1}: {output_examples[i]}")
        sections.append("\n".join(example_lines))

    sections.append(
        "不足情報がある場合は、もっとも重要な確認事項だけを短く尋ねてください。"
    )
    return "\n\n".join(section for section in sections if section)


def _parse_page_size(raw_value: str | None) -> int:
    if raw_value is None:
        return CHAT_HISTORY_PAGE_SIZE_DEFAULT
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return CHAT_HISTORY_PAGE_SIZE_DEFAULT
    if parsed < 1:
        return CHAT_HISTORY_PAGE_SIZE_DEFAULT
    return min(parsed, CHAT_HISTORY_PAGE_SIZE_MAX)


def _parse_before_message_id(raw_value: str | None) -> int | None:
    if raw_value is None or raw_value == "":
        return None
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return None
    if parsed < 1:
        return None
    return parsed


def _fetch_chat_history(
    chat_room_id: str,
    limit: int,
    before_message_id: int | None = None,
) -> dict[str, Any]:
    # API返却向けにチャット履歴をページ単位で整形する
    # Fetch and format paginated chat history for API response.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT id, message, sender, timestamp
            FROM (
                SELECT id, message, sender, timestamp
                FROM chat_history
                WHERE chat_room_id = %s
                  AND (%s IS NULL OR id < %s)
                ORDER BY id DESC
                LIMIT %s
            ) recent_history
            ORDER BY id ASC
        """
        cursor.execute(query, (chat_room_id, before_message_id, before_message_id, limit + 1))
        rows = cursor.fetchall()
        has_more = len(rows) > limit
        if has_more:
            rows = rows[1:]

        messages = []
        for (message_id, msg, sender, ts) in rows:
            messages.append(
                {
                    "id": message_id,
                    "message": msg,
                    "sender": sender,
                    "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

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
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _paginate_ephemeral_chat_history(
    rows: list[dict[str, str]],
    limit: int,
    before_message_id: int | None = None,
) -> dict[str, Any]:
    # 一時チャット履歴も同じAPI形式で返し、将来の拡張に備える
    # Shape guest chat history with the same pagination payload as persisted chats.
    normalized_messages = [
        {
            "id": index + 1,
            "message": row.get("content", ""),
            "sender": row.get("role", ""),
            "timestamp": "",
        }
        for index, row in enumerate(rows)
    ]
    if before_message_id is not None:
        normalized_messages = [
            message for message in normalized_messages if message["id"] < before_message_id
        ]

    has_more = len(normalized_messages) > limit
    page_messages = normalized_messages[-limit:]
    next_before_id = page_messages[0]["id"] if has_more and page_messages else None
    return {
        "messages": page_messages,
        "pagination": {
            "limit": limit,
            "has_more": has_more,
            "next_before_id": next_before_id,
        },
    }


@chat_bp.post("/api/chat", name="chat.chat")
async def chat(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ChatMessageRequest,
        error_message="'message' が必要です。",
    )
    if validation_error is not None:
        return validation_error

    user_message = payload.message
    chat_room_id = payload.chat_room_id
    model = payload.model or GEMINI_DEFAULT_MODEL

    # 非ログインユーザーの場合、新規チャット・続けてのチャットの回数としてカウント
    # Count each guest request toward daily free chat quota.
    session = request.session
    if "user_id" not in session:
        today = date.today().isoformat()
        if session.get("free_chats_date") != today:
            session["free_chats_date"] = today
            session["free_chats_count"] = 0
        if session.get("free_chats_count", 0) >= 10:
            return jsonify({"error": "1日10回までです"}, status_code=403)
        session["free_chats_count"] = session.get("free_chats_count", 0) + 1

    system_prompt = {
        "role": "system",
        "content": BASE_SYSTEM_PROMPT,
    }

    sid = None
    user_id = session.get("user_id")
    if "user_id" in session:
        try:
            payload, status_code = await run_blocking(
                validate_room_owner,
                chat_room_id,
                user_id,
                "他ユーザーのチャットルームには投稿できません",
            )
            if payload is not None:
                return jsonify(payload, status_code=status_code)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to validate chat room ownership before posting.",
            )

        escaped = html.escape(user_message)
        formatted_user_message = escaped.replace("\n", "<br>")

        await run_blocking(save_message_to_db, chat_room_id, formatted_user_message, "user")
        all_messages = await run_blocking(get_chat_room_messages, chat_room_id)
    else:
        sid = get_session_id(session)
        if not await run_blocking(ephemeral_store.room_exists, sid, chat_room_id):
            return jsonify({"error": "該当ルームが存在しません"}, status_code=404)

        escaped = html.escape(user_message)
        formatted_user_message = escaped.replace("\n", "<br>")
        await run_blocking(
            ephemeral_store.append_message, sid, chat_room_id, "user", formatted_user_message
        )
        all_messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)

    launch_request = _parse_task_launch_message(user_message)
    prompt_data = None

    if launch_request and len(all_messages) == 1:
        # 初回タスク起動時のみ、選択タスクの定義を補助 system prompt として追加する
        # Only the first task-launch message receives task metadata as extra system guidance.
        prompt_data = await _load_task_prompt_data(launch_request["task"], user_id)

    conversation_messages = []

    if prompt_data:
        conversation_messages.append(
            {
                "role": "system",
                "content": BASE_SYSTEM_PROMPT,
            }
        )
        conversation_messages.append(
            {
                "role": "system",
                "content": _build_task_prompt(prompt_data),
            }
        )
    else:
        conversation_messages.append(system_prompt)

    conversation_messages += all_messages

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    if has_active_generation(generation_key):
        return jsonify(
            {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
            status_code=409,
        )

    can_access_llm, _, daily_limit = await run_blocking(consume_llm_daily_quota)
    if not can_access_llm:
        return jsonify(
            {
                "error": (
                    f"本日のLLM API利用上限（全ユーザー合計 {daily_limit} 回）に達しました。"
                    "日付が変わってから再度お試しください。"
                )
            },
            status_code=429,
        )

    if is_streaming_model(model):
        persist_response = (
            partial(save_message_to_db, chat_room_id, sender="assistant")
            if "user_id" in session
            else partial(ephemeral_store.append_message, sid, chat_room_id, "assistant")
        )

        try:
            job = start_generation_job(
                generation_key,
                conversation_messages=conversation_messages,
                model=model,
                persist_response=persist_response,
            )
        except ChatGenerationAlreadyRunningError:
            return jsonify(
                {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
                status_code=409,
            )

        return _build_llm_stream_response(job)

    try:
        bot_reply = await run_blocking(get_llm_response, conversation_messages, model)
    except LlmInvalidModelError as exc:
        return jsonify({"error": str(exc)}, status_code=400)
    except LlmServiceError:
        return log_and_internal_server_error(
            logger,
            "Failed to get LLM response.",
        )

    if "user_id" in session:
        await run_blocking(save_message_to_db, chat_room_id, bot_reply, "assistant")
    else:
        sid = get_session_id(session)
        await run_blocking(ephemeral_store.append_message, sid, chat_room_id, "assistant", bot_reply)

    return jsonify({"response": bot_reply})


@chat_bp.get("/api/get_chat_history", name="chat.get_chat_history")
async def get_chat_history(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    chat_room_id = request.query_params.get("room_id")
    if not chat_room_id:
        return jsonify({"error": "room_id is required"}, status_code=400)
    limit = _parse_page_size(request.query_params.get("limit"))
    before_message_id = _parse_before_message_id(request.query_params.get("before_id"))

    session = request.session
    if "user_id" in session:
        try:
            payload, status_code = await run_blocking(
                validate_room_owner,
                chat_room_id,
                session["user_id"],
                "他ユーザーのチャット履歴は見れません",
            )
            if payload is not None:
                return jsonify(payload, status_code=status_code)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to validate chat room ownership before history fetch.",
            )

        try:
            payload = await run_blocking(_fetch_chat_history, chat_room_id, limit, before_message_id)
            return jsonify(payload)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to fetch chat history.",
            )
    else:
        sid = get_session_id(session)
        if not await run_blocking(ephemeral_store.room_exists, sid, chat_room_id):
            return jsonify({"error": "該当ルームが存在しません"}, status_code=404)

        messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)
        payload = _paginate_ephemeral_chat_history(messages, limit, before_message_id)
        return jsonify(payload)


@chat_bp.get("/api/chat_generation_stream", name="chat.chat_generation_stream")
async def chat_generation_stream(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    chat_room_id = request.query_params.get("room_id")
    if not chat_room_id:
        return jsonify({"error": "room_id is required"}, status_code=400)

    session = request.session
    sid = None
    user_id = session.get("user_id")

    if user_id is not None:
        try:
            payload, status_code = await run_blocking(
                validate_room_owner,
                chat_room_id,
                user_id,
                "他ユーザーのチャット履歴は見れません",
            )
            if payload is not None:
                return jsonify(payload, status_code=status_code)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to validate chat room ownership before generation stream.",
            )
    else:
        sid = get_session_id(session)
        if not await run_blocking(ephemeral_store.room_exists, sid, chat_room_id):
            return jsonify({"error": "該当ルームが存在しません"}, status_code=404)

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    job = get_generation_job(generation_key)
    if job is None:
        return jsonify({"error": "生成ジョブが見つかりません"}, status_code=404)

    return _build_llm_stream_response(job)


@chat_bp.get("/api/chat_generation_status", name="chat.chat_generation_status")
async def chat_generation_status(request: Request):
    await run_blocking(cleanup_ephemeral_chats)
    chat_room_id = request.query_params.get("room_id")
    if not chat_room_id:
        return jsonify({"error": "room_id is required"}, status_code=400)

    session = request.session
    sid = None
    user_id = session.get("user_id")

    if user_id is not None:
        try:
            payload, status_code = await run_blocking(
                validate_room_owner,
                chat_room_id,
                user_id,
                "他ユーザーのチャット履歴は見れません",
            )
            if payload is not None:
                return jsonify(payload, status_code=status_code)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to validate chat room ownership before generation status fetch.",
            )
    else:
        sid = get_session_id(session)
        if not await run_blocking(ephemeral_store.room_exists, sid, chat_room_id):
            return jsonify({"error": "該当ルームが存在しません"}, status_code=404)

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    job = get_generation_job(generation_key)
    is_generating = job is not None and not job.is_done
    has_replayable_job = job is not None
    return jsonify({"is_generating": is_generating, "has_replayable_job": has_replayable_job})
