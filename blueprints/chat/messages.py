import asyncio
import re
import json
import html
import logging
from collections.abc import Awaitable, Callable, Iterator
from functools import partial
from typing import Any

from fastapi import Depends, Request
from starlette.responses import StreamingResponse

from services.async_utils import run_blocking
from services.background_executor import submit_background_task
from services.attached_files import (
    decode_attached_files_from_storage,
    format_attached_files_for_prompt,
)
from services.chat_use_case import ChatPostUseCase, ChatPostUseCaseDependencies
from services.context_vault_candidate_service import should_extract_context
from services.context_vault_extraction import schedule_context_extraction
from services.chat_service import (
    list_enabled_user_skills,
    delete_unanswered_user_messages,
    fetch_chat_history_page,
    get_project_context,
    get_task_prompt_data,
    get_user_by_id,
    save_message_to_db,
    get_chat_room_messages,
    get_room_web_search_contexts,
    get_active_path,
    get_active_leaf_id,
    rename_chat_room_if_current_title_in,
    switch_chat_branch,
    validate_room_owner,
)
from services.chat_context import build_context_messages
from services.chat_prompt import (
    BASE_SYSTEM_PROMPT as BASE_SYSTEM_PROMPT,
    build_base_system_prompt as _build_base_system_prompt,
    build_task_prompt as _build_task_prompt,
    build_user_profile_prompt as _build_user_profile_prompt,
)
from services.user_skills import (
    build_chat_skills_context,
    build_enabled_user_skills_prompt,
)
from services.personal_knowledge import search_personal_knowledge_for_tool
from services.selected_reference_context import (
    SelectedReferenceLookupTrace,
    augment_messages_with_selected_references_async,
)
from services.selected_reference_sources import build_selected_reference_searchers
from services.shared_prompt_lookup import search_shared_prompts_for_tool
from services.web_search import (
    deserialize_web_search_results,
    extract_prior_web_search_results,
    inject_prior_web_search_context,
)
from services.web_search_trace import (
    answer_step,
    build_web_search_trace_markdown,
    selected_reference_steps,
)
from services.generative_ui import (
    build_message_parts_context,
    decide_generative_ui_mode,
    normalize_response_with_artifact_retry,
)
from services.chat_state import (
    get_room_summary,
    list_room_memory_facts,
    rebuild_room_summary,
    remember_facts_from_message,
)
from services.chat_generation import (
    DEFAULT_SSE_HEARTBEAT_SECONDS,
    ChatGenerationAlreadyRunningError,
    ChatGenerationEvent,
    ChatGenerationService,
    ChatGenerationJob,
    ChatGenerationStreamTimeoutError,
    build_generation_key,
    cancel_generation_job,
    get_chat_generation_service,
    get_generation_job,
    has_active_generation,
    has_replayable_generation,
    iter_generation_events,
    start_generation_job,
)
from services.auth_limits import (
    AuthLimitService,
    consume_guest_chat_daily_limit,
    get_seconds_until_tomorrow,
    get_auth_limit_service,
)
from services.api_errors import ApiServiceError
from services.i18n import get_request_locale
from services.llm_daily_limit import (
    LlmDailyLimitService,
    consume_llm_daily_quota,
    get_seconds_until_daily_reset,
    get_llm_daily_limit_service,
)
from services.llm import (
    get_llm_response,
    CLAUDE_DEFAULT_MODEL,
    is_streaming_model,
    is_retryable_llm_error,
    LlmAuthenticationError,
    LlmInvalidModelError,
    LlmRateLimitError,
    LlmServiceError,
    validate_model_name,
)
from services.chat_contract import (
    CHAT_HISTORY_PAGE_SIZE_DEFAULT,
    CHAT_HISTORY_PAGE_SIZE_MAX,
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
)

from . import (
    chat_bp,
    get_session_id,
    get_guest_room_ids,
    get_temporary_user_store_key,
    register_guest_room,
    unregister_guest_room,
    cleanup_ephemeral_chats,
    ephemeral_store,
)

logger = logging.getLogger(__name__)


def _run_async_callback(coroutine_factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run an async DB callback from the generation worker thread."""
    return asyncio.run(coroutine_factory())


# リクエストから認証制限サービスを解決するヘルパー関数
# Helper function to resolve the AuthLimitService instance from the request.
def _resolve_auth_limit_service(
    request: Request,
    service: AuthLimitService | None,
) -> AuthLimitService:
    """
    リクエストまたは依存注入された値から、認証制限サービスを取得・解決します。
    Resolves the AuthLimitService instance from the request context or dependency.
    """
    if isinstance(service, AuthLimitService):
        return service
    return get_auth_limit_service(request)


# リクエストからLLMの1日あたり制限サービスを解決するヘルパー関数
# Helper function to resolve the LlmDailyLimitService instance from the request.
def _resolve_llm_daily_limit_service(
    request: Request,
    service: LlmDailyLimitService | None,
) -> LlmDailyLimitService:
    """
    リクエストまたは依存注入された値から、LLMの1日あたり制限サービスを取得・解決します。
    Resolves the LlmDailyLimitService instance from the request context or dependency.
    """
    if isinstance(service, LlmDailyLimitService):
        return service
    return get_llm_daily_limit_service(request)


# ユーザーIDまたはセッションIDに基づいてLLMクォータ制限キーを組み立てる関数
# Construct the LLM quota limit key using the user ID or session ID.
def _build_llm_quota_user_key(user_id: int | None, sid: str | None) -> str | None:
    """
    ユーザーIDまたはセッションIDに基づき、LLMクォータ制限キーを組み立てます。
    Constructs the LLM quota limit key based on user ID or session ID.
    """
    # 呼び出し元ごとにキーを区切り、1日のLLMクォータ制限を適用します
    # Per-caller key used to scope the LLM daily quota. Without this, one
    # user could burn the global per-day cap and DoS every other user.
    if user_id is not None:
        return f"user:{user_id}"
    if sid:
        return f"sid:{sid}"
    return None


# リクエストからチャット生成サービスを解決するヘルパー関数
# Helper function to resolve the ChatGenerationService instance from the request.
def _resolve_chat_generation_service(
    request: Request,
    service: ChatGenerationService | None,
) -> ChatGenerationService:
    """
    リクエストまたは依存注入された値から、チャット生成サービスを取得・解決します。
    Resolves the ChatGenerationService instance from the request context or dependency.
    """
    if isinstance(service, ChatGenerationService):
        return service
    return get_chat_generation_service(request)


# ゲストユーザー用のチャットルームアクセス権を検証する非同期関数
# Asynchronously validate the guest session's access privileges to the specified room.
async def _validate_guest_room_access(session: dict, chat_room_id: str):
    """
    ゲストセッションの指定ルームへのアクセス権を検証します。
    Validates access rights of the guest session for the specified room.
    """
    sid = get_session_id(session)
    registered_room_ids = get_guest_room_ids(session)

    # セッションに登録されていないルームIDへのアクセスは404エラー
    # If room ID is not in session registration, return 404
    if registered_room_ids and chat_room_id not in registered_room_ids:
        return sid, jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)

    # エフェメラルストアにルームが存在するか確認
    # Verify the room exists in the ephemeral store
    room_exists = await run_blocking(ephemeral_store.room_exists, sid, chat_room_id)
    if not room_exists:
        # 存在しない場合はセッションから除外して404エラー
        # Clean up registration and return 404 if not found
        unregister_guest_room(session, chat_room_id)
        return sid, jsonify({"error": ERROR_CHAT_ROOM_NOT_FOUND}, status_code=404)

    if not registered_room_ids:
        # 以前の古いセッション情報をマイグレート
        # Migrate legacy guest sessions that predate explicit room ownership tracking.
        register_guest_room(session, chat_room_id)

    return sid, None

_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)


# 引数データをJSONシリアライズして Server-Sent Event (SSE) フォーマットのバイトデータに変換する関数
# Construct a Server-Sent Event (SSE) formatted byte sequence from event data.
def _sse_event(event: str, payload: dict[str, Any], *, sequence_id: int | None = None) -> bytes:
    """
    引数データをJSONシリアライズして Server-Sent Event (SSE) フォーマットのバイトデータに変換します。
    Constructs a Server-Sent Event (SSE) formatted byte sequence from event data.
    """
    # SSE 形式で JSON ペイロードを1イベントとして返す
    # Encode one JSON payload as an SSE event.
    body = json.dumps(payload, ensure_ascii=False)
    id_line = f"id: {sequence_id}\n" if sequence_id is not None else ""
    return f"{id_line}event: {event}\ndata: {body}\n\n".encode("utf-8")


# バックグラウンドの生成ジョブイベントを Server-Sent Event (SSE) ペイロードとして反復取得するジェネレータ
# Generator that iterates and yields SSE byte sequences from a background generation job.
def _iter_llm_stream_events(
    job: ChatGenerationJob,
    *,
    after_sequence_id: int = 0,
    heartbeat_seconds: float = DEFAULT_SSE_HEARTBEAT_SECONDS,
) -> Iterator[bytes]:
    """
    バックグラウンドの生成ジョブイベントを Server-Sent Event (SSE) ペイロードとして順次読み込みます。
    Generator that iterates and yields SSE byte sequences from a background generation job.
    """
    # 生成ジョブのイベント列を SSE として配信する
    # Convert background generation job events into SSE payloads.
    for event in job.iter_events(
        after_sequence_id=after_sequence_id,
        heartbeat_seconds=heartbeat_seconds,
    ):
        if event is None:
            yield b": keepalive\n\n"
            continue
        yield _sse_event(event.event, event.payload, sequence_id=event.sequence_id)


# シリアライズされた生成ストリームイベントを Server-Sent Event (SSE) として送出するジェネレータ
# Yield serialized generation events formatted as SSE byte streams.
def _iter_serialized_stream_events(
    events: Iterator[ChatGenerationEvent | None],
) -> Iterator[bytes]:
    """
    シリアライズされた生成ストリームイベントを Server-Sent Event (SSE) ペイロードとして送出します。
    Yields serialized generation events formatted as SSE byte streams.
    """
    try:
        for event in events:
            if event is None:
                yield b": keepalive\n\n"
                continue
            yield _sse_event(event.event, event.payload, sequence_id=event.sequence_id)
    except ChatGenerationStreamTimeoutError as exc:
        yield _sse_event("error", exc.payload)


# SSEストリーミングイベントのリストを StreamingResponse インスタンスに変換する関数
# Construct a StreamingResponse object from a sequence of SSE stream events.
def _build_llm_stream_response(
    events: Iterator[bytes],
) -> StreamingResponse:
    """
    ストリーミングイベントシーケンスから text/event-stream 形式の StreamingResponse を生成します。
    Constructs a StreamingResponse object from a sequence of SSE stream events.
    """
    # バックグラウンド生成ジョブを StreamingResponse へ変換して SSE 配信する
    # Wrap the background generation job with StreamingResponse for SSE delivery.

    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# 返答が付かなかった末尾のユーザー発話を破棄する関数（ルーム自体は残す）
# Discard the trailing user messages that never got a reply (the room is kept).
async def _discard_unanswered_user_messages(
    chat_room_id: str,
    *,
    user_id: int | None = None,
    sid: str | None = None,
) -> bool:
    """
    返答が付かなかった末尾のユーザー発話を破棄します。
    Discards the trailing user messages that never received a reply.
    """
    discarded = False
    if user_id is not None:
        discarded = await delete_unanswered_user_messages(chat_room_id, user_id) or discarded
    if sid is not None:
        discarded = await run_blocking(
            ephemeral_store.delete_unanswered_user_messages,
            sid,
            chat_room_id,
        ) or discarded
    return discarded


# エラー等で生成に失敗した際、返答が付かなかったユーザー発話を安全に掃除する関数
# Safely discard the unanswered user messages left behind by a failed generation.
async def _cleanup_unanswered_user_messages(
    chat_room_id: str,
    *,
    user_id: int | None = None,
    sid: str | None = None,
) -> None:
    """
    生成に失敗したターンのユーザー発話を掃除します。ルームは残すため、そのまま会話を続けられます。
    Cleans up the user messages of a failed turn. The room is kept so the user can keep chatting.
    """
    try:
        discarded = await _discard_unanswered_user_messages(
            chat_room_id,
            user_id=user_id,
            sid=sid,
        )
        if discarded:
            logger.info(
                "Discarded unanswered user messages after failed generation.",
                extra={"chat_room_id": chat_room_id, "user_id": user_id, "sid": sid},
            )
    except Exception:
        logger.exception(
            "Failed to discard unanswered user messages after failed generation.",
            extra={"chat_room_id": chat_room_id, "user_id": user_id, "sid": sid},
        )


# リクエストヘッダーまたはパラメータから直近 of SSEイベントIDをパース取得する関数
# Extract and parse the last SSE event ID from request headers or query parameters.
def _parse_last_event_id(request: Request) -> int:
    """
    リクエストヘッダーまたはパラメータから直近のSSEイベントIDをパース・取得します。
    Extracts and parses the last SSE event ID from request headers or query parameters.
    """
    raw_value = request.headers.get("last-event-id")
    if raw_value is None:
        raw_value = request.query_params.get("last_event_id")
    if raw_value is None:
        return 0
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


# ユーザーメッセージからタスク名と状況設定情報を抽出するパース関数
# Parse and extract task launch parameters from a user message content.
def _parse_task_launch_message(message: str) -> dict[str, Any] | None:
    """
    ユーザーメッセージから「【タスク】」や「【状況・作業環境】」の定義を検索・パースします。
    Parses and extracts task launch parameters from a user message content.
    """
    # 初回タスク起動メッセージからタスク名と状況情報を抽出する
    # Extract task name and setup info from the initial task-launch payload.
    if not message:
        return None

    task_match = re.search(r"^【タスク】(?P<task>[^\n]+)", message, re.MULTILINE)
    if not task_match:
        return None

    setup_match = re.search(r"【状況・作業環境】(?P<setup>[\s\S]+)", message)
    setup_info = setup_match.group("setup").strip() if setup_match else ""
    parsed: dict[str, Any] = {
        "task": task_match.group("task").strip(),
        "setup_info": setup_info,
    }
    task_id_match = re.search(r"^【タスクID】(?P<task_id>\d+)[ \t]*$", message, re.MULTILINE)
    if task_id_match:
        task_id = int(task_id_match.group("task_id"))
        if task_id > 0:
            parsed["task_id"] = task_id
    return parsed


# 特定タスクのプロンプトデータをDBから非同期に読み込む関数
# Asynchronously load prompt data for a specific task.
async def _load_task_prompt_data(
    task: str,
    user_id: int | None,
    task_id: int | None = None,
) -> dict[str, Any] | None:
    """
    特定タスクのプロンプト定義データを非同期でロードします。
    Asynchronously loads prompt data for a specific task.
    """
    # タスク補助情報の取得失敗ではチャット全体を止めず、ベースプロンプトのみで続行する
    # Do not fail the whole chat request when task metadata lookup fails.
    try:
        prompt_data = await get_task_prompt_data(task, user_id, task_id)
    except Exception:
        logger.exception("Failed to load task prompt metadata for task launch: %s", task)
        return None

    if prompt_data is None:
        return None
    if not isinstance(prompt_data, dict):
        logger.warning("Ignoring malformed task prompt metadata for task launch: %s", task)
        return None
    return prompt_data


async def _load_project_context_for_room(
    user_id: int | None,
    room_mode: str,
    chat_room_id: str,
) -> str | None:
    """
    チャットルームが所属するプロジェクトの指示を取得します（regenerate/edit 用）。
    Load the owning project's instructions for a room (used by regenerate/edit).
    取得に失敗しても応答生成は継続し、プロジェクト文脈のみが欠ける扱いにする。
    On failure, generation continues; only the project context is omitted.
    """
    if user_id is None or room_mode != "normal":
        return None
    try:
        project_context = await get_project_context(chat_room_id)
    except Exception:
        logger.warning("Failed to load project context; proceeding without it.")
        return None
    if not project_context:
        return None
    return str(project_context.get("instructions") or "") or None


# LLMに入力するメッセージコンテンツ（HTMLタグなど）を正規化する関数
# Normalize message text representation for LLM ingestion (such as converting <br> to newlines).
def _normalize_message_content_for_llm(content: str, role: str) -> str:
    """
    メッセージ内のHTML改行タグや実体参照を通常改行にデコード・正規化します。
    Normalizes message text representation for LLM ingestion.
    """
    normalized = content if isinstance(content, str) else str(content)
    if role == "user":
        normalized = html.unescape(normalized)
        normalized = _HTML_BR_PATTERN.sub("\n", normalized)
    return normalized


# LLM送信用に履歴メッセージリスト全体を正規化・整形する関数
# Format and normalize a list of message objects for LLM consumption.
def _normalize_messages_for_llm(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    会話履歴全体のロールやテキストデータをLLM送信用にデコード・標準化します。
    Formats and normalizes a list of message objects for LLM consumption.
    """
    normalized_messages: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        normalized_message: dict[str, Any] = {
            "role": role,
            "content": _normalize_message_content_for_llm(message.get("content", ""), role),
        }
        # Artifact source is intentionally not replayed to the model. A compact
        # description keeps follow-up requests such as "edit that chart" grounded
        # without consuming the context window with HTML/CSS/JavaScript.
        message_parts_context = build_message_parts_context(message.get("message_parts"))
        if message_parts_context:
            normalized_message["content"] += message_parts_context
        attached_file_contents = message.get("attached_file_contents")
        if attached_file_contents:
            normalized_message["attached_file_contents"] = attached_file_contents
        normalized_messages.append(normalized_message)
    return normalized_messages


# 添付済みユーザーメッセージの先頭に添付ファイルテキスト情報を埋め込む関数
# Prepend formatted attachment representations to each user message that owns them.
def _prepend_attached_files_to_user_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    履歴内の添付済みユーザーメッセージそれぞれに、参照用の添付本文を挿入します。
    Prepends reference attachment content to every user message that owns an upload.
    """
    updated_messages = list(messages)
    for index, message in enumerate(messages):
        if str(message.get("role", "")) != "user":
            continue
        attached_files = decode_attached_files_from_storage(
            message.get("attached_file_contents")
        )
        if not attached_files:
            continue
        prefix = format_attached_files_for_prompt(attached_files)
        updated_message = dict(message)
        updated_message["content"] = f"{prefix}\n\n{message.get('content', '')}"
        updated_messages[index] = updated_message
    return updated_messages


# メッセージ履歴から最も新しいタスク起動リクエストを検索抽出する関数
# Search and extract the most recent task launch request from conversation history.
def _find_latest_task_launch_request(messages: list[dict[str, str]]) -> dict[str, Any] | None:
    """
    会話履歴を逆順でスキャンし、最も新しいユーザーメッセージからタスク起動情報を抽出します。
    Searches and extracts the most recent task launch request from conversation history.
    """
    for message in reversed(messages):
        if str(message.get("role", "")) != "user":
            continue
        parsed = _parse_task_launch_message(str(message.get("content", "")))
        if parsed is not None:
            return parsed
    return None


# クエリ値から履歴取得件数をパースし制限値内にクランプする関数
# Parse limit query parameter and clamp to standard bounds for history paging.
def _parse_page_size(raw_value: str | None) -> int:
    """
    クエリパラメータから履歴取得件数をパースし、既定の上限と下限の範囲内に制限します。
    Parses limit query parameter and clamps to standard bounds for history paging.
    """
    if raw_value is None:
        return CHAT_HISTORY_PAGE_SIZE_DEFAULT
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return CHAT_HISTORY_PAGE_SIZE_DEFAULT
    if parsed < 1:
        return CHAT_HISTORY_PAGE_SIZE_DEFAULT
    return min(parsed, CHAT_HISTORY_PAGE_SIZE_MAX)


# 履歴取得時の上限基準点となるメッセージIDをパースする関数
# Parse message ID parameter serving as paging bounds for history retrieval.
def _parse_before_message_id(raw_value: str | None) -> int | None:
    """
    ページングの基準点となるメッセージIDをクエリ値からパースします。
    Parses message ID parameter serving as paging bounds for history retrieval.
    """
    if raw_value is None or raw_value == "":
        return None
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return None
    if parsed < 1:
        return None
    return parsed


# レガシーなエラーレスポンス形式を FastAPI 互換の JSONResponse に整形するヘルパー関数
# Format a legacy error response payload into a FastAPI-compatible response.
def _legacy_error_response(result: Any):
    """
    レガシーな検証結果のタプル (payload, status_code) を、FastAPI 互換のJSONResponseに整形します。
    Formats a legacy error response payload into a FastAPI-compatible response.
    """
    if not (isinstance(result, tuple) and len(result) == 2):
        return None
    payload, status_code = result
    if payload is None:
        return None
    if isinstance(payload, dict) and isinstance(status_code, int):
        return jsonify(payload, status_code=status_code)
    return None


# 認証結果からチャットルームのモード("normal" または "temporary")を判定する関数
# Resolve room mode ("normal" or "temporary") based on ownership resolution.
def _resolved_room_mode(owner_result: Any) -> str:
    """
    所有権検証結果から対象ルームのモード("normal" または "temporary")を特定します。
    Resolves room mode ("normal" or "temporary") based on ownership resolution.
    """
    if isinstance(owner_result, str) and owner_result in {"normal", "temporary"}:
        return owner_result
    return "normal"


# ゲスト用の一時チャットルームがEphemeralStoreに存在することを保証する関数
# Ensure that a guest ephemeral chat room is properly initialized in storage.
def _ensure_ephemeral_room(sid: str, chat_room_id: str, title: str = "新規チャット") -> None:
    """
    一時ストアにゲスト用のチャットルームが確実に初期化されていることを保証します。
    Ensures that a guest ephemeral chat room is properly initialized in storage.
    """
    if ephemeral_store.room_exists(sid, chat_room_id):
        return
    ephemeral_store.create_room(sid, chat_room_id, title)


# 認証されたユーザーの対象チャットルームとその所有権・モードを解決する関数
# Resolve the chat room details, ownership, and mode for authenticated requests.
async def _resolve_authenticated_room_target(
    chat_room_id: str,
    user_id: int,
    forbidden_message: str,
) -> tuple[str | None, str | None, Any]:
    """
    ユーザーIDに基づき、指定ルームのモード("normal"/"temporary")、一時ストアキーを検証・解決します。
    Resolves the chat room details, ownership, and mode for authenticated requests.
    """
    temporary_sid = get_temporary_user_store_key(user_id)
    if await run_blocking(ephemeral_store.room_exists, temporary_sid, chat_room_id):
        return "temporary", temporary_sid, None

    owner_result = await validate_room_owner(chat_room_id, user_id, forbidden_message)
    legacy_response = _legacy_error_response(owner_result)
    if legacy_response is not None:
        return None, None, legacy_response

    room_mode = _resolved_room_mode(owner_result)
    if room_mode == "temporary":
        return room_mode, temporary_sid, None
    return room_mode, None, None


# 指定されたルームIDのチャット履歴（メッセージ配列）を取得する関数
# Fetch chat messages history for the specified room.
async def _fetch_chat_history(
    chat_room_id: str,
    limit: int,
    before_message_id: int | None = None,
) -> dict[str, Any]:
    """
    リポジトリから指定されたルームIDの永続化チャット履歴をページネーション付きで取得します。
    Fetch chat messages history for the specified room.
    """
    # API返却向けにチャット履歴をページ単位で整形する
    # Fetch and format paginated chat history for API response.
    return await fetch_chat_history_page(
        chat_room_id,
        limit,
        before_message_id,
    )


# ゲストの一時チャット履歴をページング形式で取得する関数
# Paginate history from guest ephemeral chat store.
def _paginate_ephemeral_chat_history(
    rows: list[dict[str, str]],
    limit: int,
    before_message_id: int | None = None,
) -> dict[str, Any]:
    """
    ゲスト用の一時チャット履歴リストを、永続チャット履歴APIと同様のスキーマ形式にページング整形します。
    Paginates history from guest ephemeral chat store.
    """
    # 一時チャット履歴も同じAPI形式で返し、将来の拡張に備える
    # Shape guest chat history with the same pagination payload as persisted chats.
    normalized_messages = [
        {
            "id": index + 1,
            "message": row.get("content", ""),
            **({"message_parts": row.get("message_parts")} if row.get("message_parts") else {}),
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


# チャットメッセージ投稿ユースケースクラスの依存関係を満たしたインスタンスを生成する関数
# Factory function to build ChatPostUseCase instance with resolved dependencies.
def _build_chat_post_use_case(locale: str = "ja") -> ChatPostUseCase:
    """
    チャットメッセージ投稿ユースケースクラスの依存関係を満たしたインスタンスを生成します。
    Factory function to build ChatPostUseCase instance with resolved dependencies.
    """
    return ChatPostUseCase(
        ChatPostUseCaseDependencies(
            cleanup_ephemeral_chats=cleanup_ephemeral_chats,
            require_json_dict=require_json_dict,
            validate_payload_model=validate_payload_model,
            jsonify=jsonify,
            jsonify_rate_limited=jsonify_rate_limited,
            jsonify_service_error=jsonify_service_error,
            log_and_internal_server_error=log_and_internal_server_error,
            validate_model_name=validate_model_name,
            consume_guest_chat_daily_limit=consume_guest_chat_daily_limit,
            get_seconds_until_tomorrow=get_seconds_until_tomorrow,
            validate_guest_room_access=_validate_guest_room_access,
            resolve_authenticated_room_target=_resolve_authenticated_room_target,
            ensure_ephemeral_room=_ensure_ephemeral_room,
            get_temporary_user_store_key=get_temporary_user_store_key,
            ephemeral_store=ephemeral_store,
            save_message_to_db=save_message_to_db,
            get_active_leaf_id=get_active_leaf_id,
            get_chat_room_messages=get_chat_room_messages,
            get_room_web_search_contexts=get_room_web_search_contexts,
            normalize_messages_for_llm=_normalize_messages_for_llm,
            find_latest_task_launch_request=_find_latest_task_launch_request,
            load_task_prompt_data=_load_task_prompt_data,
            build_task_prompt=_build_task_prompt,
            get_user_by_id=get_user_by_id,
            build_user_profile_prompt=_build_user_profile_prompt,
            get_room_summary=get_room_summary,
            list_room_memory_facts=list_room_memory_facts,
            remember_facts_from_message=remember_facts_from_message,
            rename_chat_room_if_current_title_in=rename_chat_room_if_current_title_in,
            load_project_context=get_project_context,
            build_context_messages=build_context_messages,
            build_base_system_prompt=partial(_build_base_system_prompt, locale=locale),
            build_generation_key=build_generation_key,
            has_active_generation=has_active_generation,
            consume_llm_daily_quota=consume_llm_daily_quota,
            cleanup_unanswered_user_messages=_cleanup_unanswered_user_messages,
            get_seconds_until_daily_reset=get_seconds_until_daily_reset,
            is_streaming_model=is_streaming_model,
            search_personal_knowledge=search_personal_knowledge_for_tool,
            search_shared_prompts=search_shared_prompts_for_tool,
            start_generation_job=start_generation_job,
            build_llm_stream_response=_build_llm_stream_response,
            iter_llm_stream_events=_iter_llm_stream_events,
            get_llm_response=get_llm_response,
            decide_generative_ui_mode=decide_generative_ui_mode,
            is_retryable_llm_error=is_retryable_llm_error,
            rebuild_room_summary=rebuild_room_summary,
            should_extract_context=should_extract_context,
            schedule_context_extraction=schedule_context_extraction,
            submit_background_task=submit_background_task,
            get_session_id=get_session_id,
            logger=logger,
            load_enabled_user_skills=list_enabled_user_skills,
            build_user_skills_prompt=build_enabled_user_skills_prompt,
        ),
        default_model=CLAUDE_DEFAULT_MODEL,
        locale=locale,
    )


# ユーザーから新規メッセージを投稿し、非同期でAIの応答を開始するAPIエンドポイント
# API endpoint to post a new chat message and start asynchronous AI response generation.
@chat_bp.post("/api/chat", name="chat.chat")
async def chat(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
    chat_generation_service: ChatGenerationService | None = Depends(get_chat_generation_service),
):
    """
    新規のチャットメッセージを投稿し、AIの回答生成プロセスを起動します。
    Posts a new user message and triggers AI response generation.
    """
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    resolved_llm_daily_limit_service = _resolve_llm_daily_limit_service(
        request,
        llm_daily_limit_service,
    )
    resolved_chat_generation_service = _resolve_chat_generation_service(
        request,
        chat_generation_service,
    )
    return await _build_chat_post_use_case(get_request_locale(request)).execute(
        request,
        auth_limit_service=resolved_auth_limit_service,
        llm_daily_limit_service=resolved_llm_daily_limit_service,
        chat_generation_service=resolved_chat_generation_service,
    )


# 指定されたAIメッセージに対する再生成処理を開始するAPIエンドポイント
# API endpoint to regenerate the response for a specific assistant message.
@chat_bp.post("/api/chat_regenerate", name="chat.chat_regenerate")
async def chat_regenerate(
    request: Request,
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
    chat_generation_service: ChatGenerationService | None = Depends(get_chat_generation_service),
):
    """
    指定されたAI返答メッセージに対する再生成を開始します。DB保存ルームの場合、新たなメッセージブランチを作成します。
    Initiates regeneration of the assistant response for the target message.
    """
    resolved_llm_daily_limit_service = _resolve_llm_daily_limit_service(request, llm_daily_limit_service)
    resolved_chat_generation_service = _resolve_chat_generation_service(request, chat_generation_service)

    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    chat_room_id_raw = data.get("chat_room_id")
    model_raw = data.get("model") or CLAUDE_DEFAULT_MODEL
    # 再生成でも、送信時と同じようにメモ/マイコンテキストを参照できるようにする。
    # Regeneration consults memos and My Context on the same terms as the original send.
    use_personal_knowledge = bool(data.get("use_personal_knowledge"))
    use_shared_prompts = bool(data.get("use_shared_prompts"))

    if not isinstance(chat_room_id_raw, str) or not chat_room_id_raw.strip():
        return jsonify({"error": "chat_room_id is required"}, status_code=400)
    chat_room_id = chat_room_id_raw.strip()

    try:
        validate_model_name(model_raw)
    except LlmInvalidModelError as exc:
        return jsonify({"error": str(exc)}, status_code=400)
    model = model_raw

    session = request.session
    sid = None
    room_mode = "temporary"
    user_id = session.get("user_id")
    # For DB-backed rooms, regeneration adds a sibling assistant answer (a new
    # branch) under the same user message instead of deleting the old answer.
    assistant_parent_id: int | None = None

    if "user_id" in session:
        try:
            room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
                chat_room_id,
                user_id,
                "他ユーザーのチャットルームには投稿できません",
            )
            if legacy_response is not None:
                return legacy_response
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(logger, "Failed to validate chat room ownership for regenerate.")

        if room_mode == "temporary":
            sid = get_temporary_user_store_key(user_id)
            await run_blocking(ephemeral_store.delete_last_assistant_message, sid, chat_room_id)
            all_messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)
        else:
            path = await get_active_path(
                chat_room_id,
                include_attachment_contents=True,
            )
            if path and path[-1]["sender"] == "assistant" and len(path) >= 2:
                assistant_parent_id = path[-2]["id"]
            # Exclude the existing answer from the context so it is regenerated.
            if path and path[-1]["sender"] == "assistant":
                path = path[:-1]
            all_messages = []
            for node in path:
                entry = {
                    "role": "user" if node["sender"] == "user" else "assistant",
                    "content": node["message"],
                }
                if node.get("attached_file_contents"):
                    entry["attached_file_contents"] = node["attached_file_contents"]
                if node.get("message_parts"):
                    entry["message_parts"] = node["message_parts"]
                all_messages.append(entry)
    else:
        sid, guest_error = await _validate_guest_room_access(session, chat_room_id)
        if guest_error is not None:
            return guest_error
        await run_blocking(ephemeral_store.delete_last_assistant_message, sid, chat_room_id)
        all_messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)

    normalized_all_messages = _normalize_messages_for_llm(all_messages)
    selected_reference_query = next(
        (
            str(message.get("content") or "")
            for message in reversed(normalized_all_messages)
            if message.get("role") == "user"
        ),
        "",
    )
    normalized_all_messages = _prepend_attached_files_to_user_messages(
        normalized_all_messages
    )
    active_task_request = _find_latest_task_launch_request(normalized_all_messages)
    prompt_data = None
    if active_task_request is not None:
        task_id = active_task_request.get("task_id")
        if task_id is None:
            prompt_data = await _load_task_prompt_data(active_task_request["task"], user_id)
        else:
            prompt_data = await _load_task_prompt_data(active_task_request["task"], user_id, task_id)

    task_prompt = _build_task_prompt(prompt_data) if prompt_data else None
    enabled_user_skills: list[dict[str, Any]] = []
    room_summary = ""
    memory_facts: list[str] = []
    user = None
    user_profile_prompt = None

    if user_id is not None:
        try:
            enabled_user_skills = list(await list_enabled_user_skills(user_id))
        except Exception:
            logger.warning("Failed to load enabled user skills; proceeding without them.")
        try:
            user = await get_user_by_id(user_id)
            user_profile_prompt = _build_user_profile_prompt(user)
        except Exception:
            logger.warning("Failed to load user profile context for regenerate; proceeding without it.")

    request_locale = get_request_locale(request)
    user_skills_prompt, generative_ui_enabled = build_chat_skills_context(
        enabled_user_skills,
        user,
        locale=request_locale,
    )

    project_instructions = await _load_project_context_for_room(
        user_id, room_mode, chat_room_id
    )

    if user_id is not None and room_mode == "normal":
        try:
            summary_payload = await get_room_summary(chat_room_id)
            room_summary = str((summary_payload or {}).get("summary") or "")
        except Exception:
            logger.warning("Failed to load room summary for regenerate; proceeding without it.")
        try:
            memory_facts = await list_room_memory_facts(chat_room_id)
        except Exception:
            logger.warning("Failed to load memory facts for regenerate; proceeding without them.")

    conversation_messages = build_context_messages(
        base_system_prompt=_build_base_system_prompt(locale=request_locale),
        user_profile_prompt=user_profile_prompt,
        task_prompt=task_prompt,
        room_summary=room_summary,
        memory_facts=memory_facts,
        recent_messages=normalized_all_messages,
        project_instructions=project_instructions,
        user_skills_prompt=user_skills_prompt,
        generative_ui_enabled=generative_ui_enabled,
    )

    # 過去ターンで取得した検索結果を読み込み、再生成時にも参照用文脈として再注入する
    # Load prior-turn search results so regeneration also re-injects them as reference context.
    if user_id is not None and room_mode == "normal":
        prior_web_search_results = deserialize_web_search_results(
            await get_room_web_search_contexts(chat_room_id)
        )
    else:
        prior_web_search_results = extract_prior_web_search_results(all_messages)

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    if has_active_generation(generation_key, service=resolved_chat_generation_service):
        return jsonify(
            {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
            status_code=409,
        )

    can_access_llm, _, daily_limit = await run_blocking(
        consume_llm_daily_quota,
        service=resolved_llm_daily_limit_service,
        user_key=_build_llm_quota_user_key(user_id, sid),
    )
    if not can_access_llm:
        return jsonify_rate_limited(
            (
                f"本日のLLM API利用上限（1ユーザーあたり {daily_limit} 回）に達しました。"
                "日付が変わってから再度お試しください。"
            ),
            retry_after=get_seconds_until_daily_reset(),
        )

    selected_references = build_selected_reference_searchers(
        user_id=user_id,
        use_personal_knowledge=use_personal_knowledge,
        use_shared_prompts=use_shared_prompts,
        search_personal_knowledge=search_personal_knowledge_for_tool,
        search_shared_prompts=search_shared_prompts_for_tool,
    )
    personal_knowledge_search = selected_references.personal_knowledge
    shared_prompt_search = selected_references.shared_prompt
    selected_reference_trace: list[SelectedReferenceLookupTrace] = []
    conversation_messages = await augment_messages_with_selected_references_async(
        conversation_messages,
        query=selected_reference_query,
        personal_knowledge_search=personal_knowledge_search,
        shared_prompt_search=shared_prompt_search,
        unavailable_sources=selected_references.unavailable_sources,
        trace_results=selected_reference_trace,
    )
    if generative_ui_enabled:
        try:
            ui_mode = await run_blocking(
                decide_generative_ui_mode,
                conversation_messages,
                model,
            )
        except Exception:
            logger.warning(
                "Failed to decide generative UI mode for regeneration; continuing without intent recovery.",
                exc_info=True,
            )
            ui_mode = None
    else:
        ui_mode = "NONE"

    if is_streaming_model(model):
        on_finished = None
        if user_id is not None and room_mode == "normal":
            # 生成された回答テキストをDBまたは一時ストアに保存する内部ヘルパー
            # Save generated response text into DB or ephemeral store.
            def persist_response(
                response: str,
                *,
                message_parts: list[dict[str, Any]] | None = None,
                web_search_context: list[dict[str, Any]] | None = None,
            ) -> None:
                _run_async_callback(
                    lambda: save_message_to_db(
                        chat_room_id,
                        response,
                        "assistant",
                        None,
                        assistant_parent_id,
                        message_parts,
                        None,
                        web_search_context,
                    )
                )

            # 生成処理完了時にルームの会話要約やメモリを更新する内部終了ハンドラ
            # Internal callback executed upon generation completion to update summary/memory.
            def on_finished() -> None:
                try:
                    updated_messages = _run_async_callback(
                        lambda: get_chat_room_messages(chat_room_id)
                    )
                    _run_async_callback(
                        lambda: rebuild_room_summary(chat_room_id, updated_messages, model=model)
                    )
                except Exception:
                    logger.warning(
                        "Failed to rebuild room summary after regeneration for %s.", chat_room_id
                    )
        else:
            persist_response = partial(
                ephemeral_store.append_message,
                sid,
                chat_room_id,
                "assistant",
            )

        try:
            job = start_generation_job(
                generation_key,
                conversation_messages=conversation_messages,
                model=model,
                persist_response=persist_response,
                on_finished=on_finished,
                # 再生成はこのリクエストで新しいユーザー発話を保存していないため、
                # 失敗時に掃除する対象がない。掃除すると既存の発話まで消えてしまう。
                # Regeneration saves no new user message, so there is nothing to
                # clean up; running the cleanup would delete an existing message.
                service=resolved_chat_generation_service,
                prior_web_search_results=prior_web_search_results,
                personal_knowledge_search=personal_knowledge_search,
                shared_prompt_search=shared_prompt_search,
                selected_reference_trace=selected_reference_trace,
                ui_mode=ui_mode,
            )
        except ChatGenerationAlreadyRunningError:
            return jsonify(
                {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
                status_code=409,
            )

        return _build_llm_stream_response(_iter_llm_stream_events(job))

    # 非ストリーミング再生成でも過去ターンの検索結果を参照用文脈として再注入する
    # Re-inject prior-turn search results for non-streaming regeneration as well.
    conversation_messages = inject_prior_web_search_context(
        conversation_messages, prior_web_search_results
    )

    try:
        bot_reply = await run_blocking(get_llm_response, conversation_messages, model)
    except (LlmInvalidModelError, LlmRateLimitError, LlmAuthenticationError, LlmServiceError) as exc:
        # ユーザーへエラーを返す経路は必ず詳細をログへ残す。
        # Always log details on any path that surfaces an error to the user.
        logger.error(
            "Non-streaming chat generation failed for room %s (model=%s): %s",
            chat_room_id,
            model,
            exc,
            exc_info=True,
        )
        return jsonify({"error": str(exc)}, status_code=500)

    selected_steps = selected_reference_steps(selected_reference_trace)
    if selected_steps:
        trace_block = build_web_search_trace_markdown(
            steps=[*selected_steps, answer_step([])],
        )
        bot_reply = f"{trace_block}\n\n{bot_reply}" if bot_reply else trace_block

    latest_user_message = next(
        (
            str(message.get("content") or "")
            for message in reversed(conversation_messages)
            if message.get("role") == "user"
        ),
        "",
    )
    normalized_response = await run_blocking(
        partial(
            normalize_response_with_artifact_retry,
            conversation_messages=conversation_messages,
            model=model,
            generate_response=get_llm_response,
            user_request=latest_user_message,
            ui_mode=ui_mode,
        ),
        bot_reply,
    )
    if normalized_response.validation_errors:
        logger.warning(
            "One or more generated UI artifacts failed validation and were omitted.",
            extra={"validation_errors": normalized_response.validation_errors},
        )
    bot_reply = normalized_response.text
    message_parts = normalized_response.parts

    if user_id is not None and room_mode == "normal":
        save_args = [
            chat_room_id,
            bot_reply,
            "assistant",
            None,
            assistant_parent_id,
        ]
        if message_parts:
            save_args.append(message_parts)
        await save_message_to_db(*save_args)
    elif sid is not None:
        append_args = [sid, chat_room_id, "assistant", bot_reply]
        if message_parts:
            append_args.append(message_parts)
        await run_blocking(
            ephemeral_store.append_message,
            *append_args,
        )

    response_payload = {"response": bot_reply}
    if message_parts:
        response_payload["parts"] = message_parts
    return jsonify(response_payload)


# 過去のユーザーメッセージを編集し、それに続く新しいブランチで再生成を開始するAPIエンドポイント
# API endpoint to edit a previous user message and generate a new conversation branch.
@chat_bp.post("/api/chat_edit_and_regenerate", name="chat.chat_edit_and_regenerate")
async def chat_edit_and_regenerate(
    request: Request,
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
    chat_generation_service: ChatGenerationService | None = Depends(get_chat_generation_service),
):
    """
    過去のユーザーメッセージを編集し、そこからの分岐（ブランチ）で新しいAI応答の生成を開始します。
    Edits a previous user message and spawns a new branch with a regenerated AI response.
    """
    resolved_llm_daily_limit_service = _resolve_llm_daily_limit_service(request, llm_daily_limit_service)
    resolved_chat_generation_service = _resolve_chat_generation_service(request, chat_generation_service)

    await run_blocking(cleanup_ephemeral_chats)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    chat_room_id_raw = data.get("chat_room_id")
    new_message_raw = data.get("new_message")
    model_raw = data.get("model") or CLAUDE_DEFAULT_MODEL
    trailing_user_count_raw = data.get("trailing_user_count")
    # 編集して再生成する場合も、送信時と同じようにメモ/マイコンテキストを参照できるようにする。
    # Editing and regenerating consults memos and My Context on the same terms as the original send.
    use_personal_knowledge = bool(data.get("use_personal_knowledge"))
    use_shared_prompts = bool(data.get("use_shared_prompts"))

    if not isinstance(chat_room_id_raw, str) or not chat_room_id_raw.strip():
        return jsonify({"error": "chat_room_id is required"}, status_code=400)
    chat_room_id = chat_room_id_raw.strip()

    if not isinstance(new_message_raw, str) or not new_message_raw.strip():
        return jsonify({"error": "new_message is required"}, status_code=400)
    new_message = new_message_raw.strip()

    if not isinstance(trailing_user_count_raw, int) or trailing_user_count_raw < 0:
        return jsonify({"error": "trailing_user_count must be a non-negative integer"}, status_code=400)
    trailing_user_count = trailing_user_count_raw

    try:
        validate_model_name(model_raw)
    except LlmInvalidModelError as exc:
        return jsonify({"error": str(exc)}, status_code=400)
    model = model_raw

    session = request.session
    sid = None
    room_mode = "temporary"
    user_id = session.get("user_id")
    formatted_user_message = html.escape(new_message).replace("\n", "<br>")
    # For DB-backed rooms, editing forks a new user message as a sibling branch
    # (the original message and its answers are preserved and remain switchable).
    assistant_parent_id: int | None = None

    if "user_id" in session:
        try:
            room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
                chat_room_id,
                user_id,
                "他ユーザーのチャットルームには投稿できません",
            )
            if legacy_response is not None:
                return legacy_response
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger, "Failed to validate chat room ownership for edit_and_regenerate."
            )

        if room_mode == "temporary":
            sid = get_temporary_user_store_key(user_id)
            existing_messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)
            user_positions = [
                i for i, message in enumerate(existing_messages)
                if message.get("role") == "user"
            ]
            if len(user_positions) <= trailing_user_count:
                return jsonify({"error": "編集対象のメッセージが見つかりません"}, status_code=404)
            target_pos = user_positions[len(user_positions) - 1 - trailing_user_count]
            target_attached_file_contents = decode_attached_files_from_storage(
                existing_messages[target_pos].get("attached_file_contents")
            )
            attachment_content_kwargs = (
                {"attached_file_contents": target_attached_file_contents}
                if target_attached_file_contents
                else {}
            )
            await run_blocking(
                ephemeral_store.delete_messages_from_trailing_user_count,
                sid,
                chat_room_id,
                trailing_user_count,
            )
            await run_blocking(
                ephemeral_store.append_message,
                sid,
                chat_room_id,
                "user",
                formatted_user_message,
                **attachment_content_kwargs,
            )
            all_messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)
        else:
            path = await get_active_path(
                chat_room_id,
                include_attachment_contents=True,
            )
            user_positions = [i for i, node in enumerate(path) if node["sender"] == "user"]
            if len(user_positions) <= trailing_user_count:
                return jsonify({"error": "編集対象のメッセージが見つかりません"}, status_code=404)
            target_pos = user_positions[len(user_positions) - 1 - trailing_user_count]
            edit_parent_id = path[target_pos - 1]["id"] if target_pos > 0 else None
            target_attached_file_names = path[target_pos].get("attached_file_names")
            target_attached_file_contents = decode_attached_files_from_storage(
                path[target_pos].get("attached_file_contents")
            )
            attachment_content_kwargs = (
                {"attached_file_contents": target_attached_file_contents}
                if target_attached_file_contents
                else {}
            )
            assistant_parent_id = await save_message_to_db(
                chat_room_id,
                formatted_user_message,
                "user",
                target_attached_file_names,
                edit_parent_id,
                **attachment_content_kwargs,
            )
            # Context = branch ancestors up to the edited point, then the new message.
            all_messages = [
                {
                    "role": "user" if node["sender"] == "user" else "assistant",
                    "content": node["message"],
                    **(
                        {"attached_file_contents": node["attached_file_contents"]}
                        if node.get("attached_file_contents")
                        else {}
                    ),
                    **(
                        {"message_parts": node["message_parts"]}
                        if node.get("message_parts")
                        else {}
                    ),
                }
                for node in path[:target_pos]
            ]
            edited_message = {"role": "user", "content": formatted_user_message}
            if target_attached_file_contents:
                edited_message["attached_file_contents"] = [
                    {
                        "name": attached_file.name,
                        "content": attached_file.content,
                    }
                    for attached_file in target_attached_file_contents
                ]
            all_messages.append(edited_message)
    else:
        sid, guest_error = await _validate_guest_room_access(session, chat_room_id)
        if guest_error is not None:
            return guest_error
        existing_messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)
        user_positions = [
            i for i, message in enumerate(existing_messages)
            if message.get("role") == "user"
        ]
        if len(user_positions) <= trailing_user_count:
            return jsonify({"error": "編集対象のメッセージが見つかりません"}, status_code=404)
        target_pos = user_positions[len(user_positions) - 1 - trailing_user_count]
        target_attached_file_contents = decode_attached_files_from_storage(
            existing_messages[target_pos].get("attached_file_contents")
        )
        attachment_content_kwargs = (
            {"attached_file_contents": target_attached_file_contents}
            if target_attached_file_contents
            else {}
        )
        await run_blocking(
            ephemeral_store.delete_messages_from_trailing_user_count,
            sid,
            chat_room_id,
            trailing_user_count,
        )
        await run_blocking(
            ephemeral_store.append_message,
            sid,
            chat_room_id,
            "user",
            formatted_user_message,
            **attachment_content_kwargs,
        )
        all_messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)

    normalized_all_messages = _normalize_messages_for_llm(all_messages)
    normalized_all_messages = _prepend_attached_files_to_user_messages(
        normalized_all_messages
    )
    active_task_request = _find_latest_task_launch_request(normalized_all_messages)
    prompt_data = None
    if active_task_request is not None:
        task_id = active_task_request.get("task_id")
        if task_id is None:
            prompt_data = await _load_task_prompt_data(active_task_request["task"], user_id)
        else:
            prompt_data = await _load_task_prompt_data(active_task_request["task"], user_id, task_id)

    task_prompt = _build_task_prompt(prompt_data) if prompt_data else None
    enabled_user_skills: list[dict[str, Any]] = []
    room_summary = ""
    memory_facts: list[str] = []
    user = None
    user_profile_prompt = None

    if user_id is not None:
        try:
            enabled_user_skills = list(await list_enabled_user_skills(user_id))
        except Exception:
            logger.warning("Failed to load enabled user skills; proceeding without them.")
        try:
            user = await get_user_by_id(user_id)
            user_profile_prompt = _build_user_profile_prompt(user)
        except Exception:
            logger.warning("Failed to load user profile for edit_and_regenerate; proceeding without it.")

    request_locale = get_request_locale(request)
    user_skills_prompt, generative_ui_enabled = build_chat_skills_context(
        enabled_user_skills,
        user,
        locale=request_locale,
    )

    project_instructions = await _load_project_context_for_room(
        user_id, room_mode, chat_room_id
    )

    if user_id is not None and room_mode == "normal":
        try:
            summary_payload = await get_room_summary(chat_room_id)
            room_summary = str((summary_payload or {}).get("summary") or "")
        except Exception:
            logger.warning("Failed to load room summary for edit_and_regenerate; proceeding without it.")
        try:
            memory_facts = await list_room_memory_facts(chat_room_id)
        except Exception:
            logger.warning("Failed to load memory facts for edit_and_regenerate; proceeding without them.")

    conversation_messages = build_context_messages(
        base_system_prompt=_build_base_system_prompt(locale=request_locale),
        user_profile_prompt=user_profile_prompt,
        task_prompt=task_prompt,
        room_summary=room_summary,
        memory_facts=memory_facts,
        recent_messages=normalized_all_messages,
        project_instructions=project_instructions,
        user_skills_prompt=user_skills_prompt,
        generative_ui_enabled=generative_ui_enabled,
    )

    # 過去ターンで取得した検索結果を読み込み、再生成時にも参照用文脈として再注入する
    # Load prior-turn search results so regeneration also re-injects them as reference context.
    if user_id is not None and room_mode == "normal":
        prior_web_search_results = deserialize_web_search_results(
            await get_room_web_search_contexts(chat_room_id)
        )
    else:
        prior_web_search_results = extract_prior_web_search_results(all_messages)

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    if has_active_generation(generation_key, service=resolved_chat_generation_service):
        return jsonify(
            {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
            status_code=409,
        )

    can_access_llm, _, daily_limit = await run_blocking(
        consume_llm_daily_quota,
        service=resolved_llm_daily_limit_service,
        user_key=_build_llm_quota_user_key(user_id, sid),
    )
    if not can_access_llm:
        return jsonify_rate_limited(
            (
                f"本日のLLM API利用上限（1ユーザーあたり {daily_limit} 回）に達しました。"
                "日付が変わってから再度お試しください。"
            ),
            retry_after=get_seconds_until_daily_reset(),
        )

    selected_references = build_selected_reference_searchers(
        user_id=user_id,
        use_personal_knowledge=use_personal_knowledge,
        use_shared_prompts=use_shared_prompts,
        search_personal_knowledge=search_personal_knowledge_for_tool,
        search_shared_prompts=search_shared_prompts_for_tool,
    )
    personal_knowledge_search = selected_references.personal_knowledge
    shared_prompt_search = selected_references.shared_prompt
    selected_reference_trace: list[SelectedReferenceLookupTrace] = []
    conversation_messages = await augment_messages_with_selected_references_async(
        conversation_messages,
        query=new_message,
        personal_knowledge_search=personal_knowledge_search,
        shared_prompt_search=shared_prompt_search,
        unavailable_sources=selected_references.unavailable_sources,
        trace_results=selected_reference_trace,
    )
    if generative_ui_enabled:
        try:
            ui_mode = await run_blocking(
                decide_generative_ui_mode,
                conversation_messages,
                model,
            )
        except Exception:
            logger.warning(
                "Failed to decide generative UI mode for edit_and_regenerate; continuing without intent recovery.",
                exc_info=True,
            )
            ui_mode = None
    else:
        ui_mode = "NONE"

    if is_streaming_model(model):
        on_finished = None
        if user_id is not None and room_mode == "normal":
            # 生成された回答テキストをDBまたは一時ストアに保存する内部ヘルパー
            # Save generated response text into DB or ephemeral store.
            def persist_response(
                response: str,
                *,
                message_parts: list[dict[str, Any]] | None = None,
                web_search_context: list[dict[str, Any]] | None = None,
            ) -> None:
                _run_async_callback(
                    lambda: save_message_to_db(
                        chat_room_id,
                        response,
                        "assistant",
                        None,
                        assistant_parent_id,
                        message_parts,
                        None,
                        web_search_context,
                    )
                )

            # 生成処理完了時にルームの会話要約やメモリを更新する内部終了ハンドラ
            # Internal callback executed upon generation completion to update summary/memory.
            def on_finished() -> None:
                try:
                    updated_messages = _run_async_callback(
                        lambda: get_chat_room_messages(chat_room_id)
                    )
                    _run_async_callback(
                        lambda: rebuild_room_summary(chat_room_id, updated_messages, model=model)
                    )
                except Exception:
                    logger.warning(
                        "Failed to rebuild room summary after edit_and_regenerate for %s.", chat_room_id
                    )
        else:
            persist_response = partial(
                ephemeral_store.append_message,
                sid,
                chat_room_id,
                "assistant",
            )

        try:
            job = start_generation_job(
                generation_key,
                conversation_messages=conversation_messages,
                model=model,
                persist_response=persist_response,
                on_finished=on_finished,
                on_error=partial(
                    _run_async_callback,
                    lambda: _cleanup_unanswered_user_messages(
                        chat_room_id,
                        user_id=user_id,
                        sid=sid,
                    ),
                ),
                service=resolved_chat_generation_service,
                prior_web_search_results=prior_web_search_results,
                personal_knowledge_search=personal_knowledge_search,
                shared_prompt_search=shared_prompt_search,
                selected_reference_trace=selected_reference_trace,
                ui_mode=ui_mode,
            )
        except ChatGenerationAlreadyRunningError:
            return jsonify(
                {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
                status_code=409,
            )

        return _build_llm_stream_response(_iter_llm_stream_events(job))

    # 非ストリーミング再生成でも過去ターンの検索結果を参照用文脈として再注入する
    # Re-inject prior-turn search results for non-streaming regeneration as well.
    conversation_messages = inject_prior_web_search_context(
        conversation_messages, prior_web_search_results
    )

    try:
        bot_reply = await run_blocking(get_llm_response, conversation_messages, model)
    except (LlmInvalidModelError, LlmRateLimitError, LlmAuthenticationError, LlmServiceError) as exc:
        # ユーザーへエラーを返す経路は必ず詳細をログへ残す。
        # Always log details on any path that surfaces an error to the user.
        logger.error(
            "Non-streaming chat generation failed for room %s (model=%s): %s",
            chat_room_id,
            model,
            exc,
            exc_info=True,
        )
        return jsonify({"error": str(exc)}, status_code=500)

    selected_steps = selected_reference_steps(selected_reference_trace)
    if selected_steps:
        trace_block = build_web_search_trace_markdown(
            steps=[*selected_steps, answer_step([])],
        )
        bot_reply = f"{trace_block}\n\n{bot_reply}" if bot_reply else trace_block

    latest_user_message = next(
        (
            str(message.get("content") or "")
            for message in reversed(conversation_messages)
            if message.get("role") == "user"
        ),
        "",
    )
    normalized_response = await run_blocking(
        partial(
            normalize_response_with_artifact_retry,
            conversation_messages=conversation_messages,
            model=model,
            generate_response=get_llm_response,
            user_request=latest_user_message,
            ui_mode=ui_mode,
        ),
        bot_reply,
    )
    if normalized_response.validation_errors:
        logger.warning(
            "One or more generated UI artifacts failed validation and were omitted.",
            extra={"validation_errors": normalized_response.validation_errors},
        )
    bot_reply = normalized_response.text
    message_parts = normalized_response.parts

    if user_id is not None and room_mode == "normal":
        save_args = [
            chat_room_id,
            bot_reply,
            "assistant",
            None,
            assistant_parent_id,
        ]
        if message_parts:
            save_args.append(message_parts)
        await save_message_to_db(*save_args)
    elif sid is not None:
        append_args = [sid, chat_room_id, "assistant", bot_reply]
        if message_parts:
            append_args.append(message_parts)
        await run_blocking(
            ephemeral_store.append_message,
            *append_args,
        )

    response_payload = {"response": bot_reply}
    if message_parts:
        response_payload["parts"] = message_parts
    return jsonify(response_payload)


# チャット会話内の指定されたアクティブなブランチ（メッセージ分岐）を切り替えるAPIエンドポイント
# API endpoint to switch the active branch in a message conversation tree.
@chat_bp.post("/api/chat_switch_branch", name="chat.chat_switch_branch")
async def chat_switch_branch(request: Request):
    """
    チャット履歴内の指定されたメッセージ分岐（編集履歴や再生成回答）へアクティブな会話ツリーパスを切り替えます。
    Switches the active conversation path to the specified message branch.
    """
    # Switch the active branch (a regenerated answer or an edited message version)
    # for a DB-backed chat room and return the resulting active conversation path.
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    chat_room_id_raw = data.get("chat_room_id")
    message_id_raw = data.get("message_id")

    if not isinstance(chat_room_id_raw, str) or not chat_room_id_raw.strip():
        return jsonify({"error": "chat_room_id is required"}, status_code=400)
    chat_room_id = chat_room_id_raw.strip()

    if not isinstance(message_id_raw, int) or message_id_raw < 1:
        return jsonify({"error": "message_id must be a positive integer"}, status_code=400)
    message_id = message_id_raw

    session = request.session
    user_id = session.get("user_id")

    if user_id is None:
        return jsonify({"error": "分岐の切り替えはログイン後のチャットでのみ利用できます"}, status_code=400)

    try:
        room_mode, _sid, legacy_response = await _resolve_authenticated_room_target(
            chat_room_id,
            user_id,
            "他ユーザーのチャットルームは操作できません",
        )
        if legacy_response is not None:
            return legacy_response
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to validate chat room ownership before branch switch.",
        )

    if room_mode != "normal":
        return jsonify(
            {"error": "一時チャットでは分岐の切り替えは利用できません"},
            status_code=400,
        )

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=None)
    if has_active_generation(generation_key, service=get_chat_generation_service(request)):
        return jsonify(
            {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
            status_code=409,
        )

    try:
        messages = await switch_chat_branch(chat_room_id, message_id)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to switch chat branch.")

    return jsonify({"messages": messages})


# 進行中のAI回答生成処理を強制停止するAPIエンドポイント
# API endpoint to abort an active AI response generation job.
@chat_bp.post("/api/chat_stop", name="chat.chat_stop")
async def chat_stop(
    request: Request,
    chat_generation_service: ChatGenerationService | None = Depends(get_chat_generation_service),
):
    """
    進行中のAI回答生成ジョブ（ストリーミング含む）をキャンセルし、停止します。
    Aborts the active AI response generation job.
    """
    # 生成中ジョブを停止する前に、対象ルームのアクセス権を再検証する
    # Re-validate room access before cancelling in-flight generation jobs.
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    chat_room_id = data.get("chat_room_id")
    if not chat_room_id:
        return jsonify({"error": "chat_room_id is required"}, status_code=400)

    session = request.session
    resolved_chat_generation_service = _resolve_chat_generation_service(
        request,
        chat_generation_service,
    )
    sid = None
    user_id = session.get("user_id")
    room_mode = "temporary"

    if user_id is not None:
        try:
            room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
                chat_room_id,
                user_id,
                "他ユーザーのチャットルームは操作できません",
            )
            if legacy_response is not None:
                return legacy_response
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to validate chat room ownership before stop.",
            )
    else:
        sid, guest_error = await _validate_guest_room_access(session, chat_room_id)
        if guest_error is not None:
            return guest_error

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    cancelled = await run_blocking(
        cancel_generation_job,
        generation_key,
        service=resolved_chat_generation_service,
    )
    return jsonify({"cancelled": cancelled})


# 指定チャットルームの履歴をページネーション付きで取得するAPIエンドポイント
# API endpoint to retrieve paginated conversation history for a chat room.
@chat_bp.get("/api/get_chat_history", name="chat.get_chat_history")
async def get_chat_history(request: Request):
    """
    指定チャットルームの会話メッセージ履歴をページネーション付きで取得します。
    Retrieves the paginated message list for a specific chat room.
    """
    # 履歴取得は常にページング形式で返し、クライアント側の遅延読み込みに合わせる
    # Always return paginated history payloads for client-side incremental loading.
    await run_blocking(cleanup_ephemeral_chats)
    chat_room_id = request.query_params.get("room_id")
    if not chat_room_id:
        return jsonify({"error": "room_id is required"}, status_code=400)
    limit = _parse_page_size(request.query_params.get("limit"))
    before_message_id = _parse_before_message_id(request.query_params.get("before_id"))

    session = request.session
    if "user_id" in session:
        room_mode = "normal"
        try:
            room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
                chat_room_id,
                session["user_id"],
                "他ユーザーのチャット履歴は見れません",
            )
            if legacy_response is not None:
                return legacy_response
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to validate chat room ownership before history fetch.",
            )

        if room_mode == "temporary":
            messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)
            payload = _paginate_ephemeral_chat_history(messages, limit, before_message_id)
            payload["room_mode"] = room_mode
            payload["summary"] = ""
            payload["memory_facts"] = []
            return jsonify(payload)

        try:
            payload = await _fetch_chat_history(chat_room_id, limit, before_message_id)
            payload["room_mode"] = room_mode
            # Keep the history endpoint lightweight so the chat view can render immediately.
            payload["summary"] = ""
            payload["memory_facts"] = []
            return jsonify(payload)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to fetch chat history.",
            )
    else:
        sid, guest_error = await _validate_guest_room_access(session, chat_room_id)
        if guest_error is not None:
            return guest_error

        messages = await run_blocking(ephemeral_store.get_messages, sid, chat_room_id)
        payload = _paginate_ephemeral_chat_history(messages, limit, before_message_id)
        payload["room_mode"] = "temporary"
        payload["summary"] = ""
        payload["memory_facts"] = []
        return jsonify(payload)


# 進行中のAI回答テキスト生成ストリームを Server-Sent Events (SSE) で配信するAPIエンドポイント
# API endpoint to stream the active generation tokens via Server-Sent Events (SSE).
@chat_bp.get("/api/chat_generation_stream", name="chat.chat_generation_stream")
async def chat_generation_stream(
    request: Request,
    chat_generation_service: ChatGenerationService | None = Depends(get_chat_generation_service),
):
    """
    進行中のAI回答生成ジョブに接続し、生成されるトークンをSSE (Server-Sent Events) 形式でストリーミングします。
    Connects to the active generation job to stream response tokens via SSE.
    """
    # 既存生成ジョブへ再接続するためのSSEエンドポイント
    # SSE endpoint for reconnecting to an existing generation job.
    await run_blocking(cleanup_ephemeral_chats)
    chat_room_id = request.query_params.get("room_id")
    if not chat_room_id:
        return jsonify({"error": "room_id is required"}, status_code=400)

    session = request.session
    resolved_chat_generation_service = _resolve_chat_generation_service(
        request,
        chat_generation_service,
    )
    sid = None
    user_id = session.get("user_id")
    room_mode = "temporary"

    if user_id is not None:
        try:
            room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
                chat_room_id,
                user_id,
                "他ユーザーのチャット履歴は見れません",
            )
            if legacy_response is not None:
                return legacy_response
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to validate chat room ownership before generation stream.",
            )
    else:
        sid, guest_error = await _validate_guest_room_access(session, chat_room_id)
        if guest_error is not None:
            return guest_error

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    last_event_id = _parse_last_event_id(request)
    job = get_generation_job(generation_key, service=resolved_chat_generation_service)
    if job is not None:
        return _build_llm_stream_response(
            _iter_llm_stream_events(job, after_sequence_id=last_event_id)
        )

    replayable = has_replayable_generation(
        generation_key,
        service=resolved_chat_generation_service,
    )
    active = has_active_generation(generation_key, service=resolved_chat_generation_service)
    if not replayable and not active:
        return jsonify({"error": "生成ジョブが見つかりません"}, status_code=404)

    if not resolved_chat_generation_service.supports_distributed_streaming():
        if active:
            return jsonify(
                {"error": "生成ジョブは進行中ですが、このインスタンスでは再接続できません。"},
                status_code=409,
            )
        return jsonify({"error": "生成ジョブが見つかりません"}, status_code=404)

    distributed_events = iter_generation_events(
        generation_key,
        after_sequence_id=last_event_id,
        service=resolved_chat_generation_service,
    )
    return _build_llm_stream_response(_iter_serialized_stream_events(distributed_events))


# 現在進行中のAI生成処理ステータスを取得するAPIエンドポイント
# API endpoint to check status of an ongoing generation job.
@chat_bp.get("/api/chat_generation_status", name="chat.chat_generation_status")
async def chat_generation_status(
    request: Request,
    chat_generation_service: ChatGenerationService | None = Depends(get_chat_generation_service),
):
    """
    対象チャットルームで現在AI回答が生成中であるかどうかのステータスを取得します。
    Checks the status of an ongoing generation job for the room.
    """
    await run_blocking(cleanup_ephemeral_chats)
    chat_room_id = request.query_params.get("room_id")
    if not chat_room_id:
        return jsonify({"error": "room_id is required"}, status_code=400)

    session = request.session
    resolved_chat_generation_service = _resolve_chat_generation_service(
        request,
        chat_generation_service,
    )
    sid = None
    user_id = session.get("user_id")
    room_mode = "temporary"

    if user_id is not None:
        try:
            room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
                chat_room_id,
                user_id,
                "他ユーザーのチャット履歴は見れません",
            )
            if legacy_response is not None:
                return legacy_response
        except ApiServiceError as exc:
            return jsonify_service_error(exc)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to validate chat room ownership before generation status fetch.",
            )
    else:
        sid, guest_error = await _validate_guest_room_access(session, chat_room_id)
        if guest_error is not None:
            return guest_error

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    is_generating = has_active_generation(
        generation_key,
        service=resolved_chat_generation_service,
    )
    has_replayable_job = has_replayable_generation(
        generation_key,
        service=resolved_chat_generation_service,
    )
    return jsonify({"is_generating": is_generating, "has_replayable_job": has_replayable_job})
