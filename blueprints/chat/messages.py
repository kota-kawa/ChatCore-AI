import html
import json
import logging
from collections.abc import Iterator
from functools import partial
from typing import Any

from fastapi import Depends, Request
from starlette.responses import StreamingResponse

from services.api_errors import ApiServiceError
from services.async_utils import iterate_blocking, run_blocking
from services.attached_files import decode_attached_files_from_storage
from services.auth_limits import (
    AuthLimitService,
    consume_guest_chat_daily_limit,
    get_auth_limit_service,
    get_seconds_until_tomorrow,
)
from services.background_executor import submit_background_task
from services.chat_context import build_context_messages
from services.chat_contract import (
    CHAT_HISTORY_PAGE_SIZE_DEFAULT,
    CHAT_HISTORY_PAGE_SIZE_MAX,
)
from services.chat_generation import (
    DEFAULT_SSE_HEARTBEAT_SECONDS,
    ChatGenerationEvent,
    ChatGenerationJob,
    ChatGenerationService,
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
from services.chat_message_normalization import (
    find_latest_task_launch_request,
    normalize_messages_for_llm,
    parse_task_launch_message,
)
from services.chat_post_dependencies import (
    ChatPostBackgroundDependencies,
    ChatPostGenerationDependencies,
    ChatPostLimitDependencies,
    ChatPostPersistenceDependencies,
    ChatPostPromptDependencies,
    ChatPostRoomDependencies,
    ChatPostUseCaseDependencies,
    ChatPostWebDependencies,
)
from services.chat_prompt import (
    BASE_SYSTEM_PROMPT as BASE_SYSTEM_PROMPT,
)
from services.chat_prompt import (
    build_base_system_prompt as _build_base_system_prompt,
)
from services.chat_prompt import (
    build_task_prompt as _build_task_prompt,
)
from services.chat_prompt import (
    build_user_profile_prompt as _build_user_profile_prompt,
)
from services.chat_regeneration_pipeline import (
    ChatRegenerationDependencies,
    ChatRegenerationInput,
    ChatRegenerationLogMessages,
    ChatRegenerationOutcome,
    ChatRegenerationRateLimited,
    ChatRegenerationRejected,
    ChatRegenerationStreamStarted,
    run_chat_regeneration,
)
from services.chat_service import (
    delete_unanswered_user_messages,
    fetch_chat_history_page,
    get_active_path,
    get_chat_room_messages,
    get_project_context,
    get_room_web_search_contexts,
    get_task_prompt_data,
    get_user_by_id,
    list_enabled_user_skills,
    rename_chat_room_if_current_title_in,
    save_message_to_db,
    store_user_message_and_load_turn_context,
    switch_chat_branch,
    validate_room_owner,
)
from services.chat_state import (
    get_room_summary,
    list_room_memory_facts,
    rebuild_room_summary,
    remember_facts_from_message,
)
from services.chat_use_case import ChatPostUseCase
from services.context_vault_candidate_service import should_extract_context
from services.context_vault_extraction import schedule_context_extraction
from services.error_messages import (
    ERROR_CHAT_ROOM_NOT_FOUND,
)
from services.generative_ui import (
    decide_generative_ui_mode,
)
from services.i18n import get_request_locale
from services.llm import (
    CLAUDE_DEFAULT_MODEL,
    LlmInvalidModelError,
    get_llm_response,
    is_retryable_llm_error,
    is_streaming_model,
    validate_model_name,
)
from services.llm_daily_limit import (
    LlmDailyLimitService,
    consume_llm_daily_quota,
    get_llm_daily_limit_service,
    get_seconds_until_daily_reset,
)
from services.personal_knowledge import search_personal_knowledge_for_tool
from services.shared_prompt_lookup import search_shared_prompts_for_tool
from services.user_skills import (
    build_enabled_user_skills_prompt,
)
from services.web import (
    jsonify,
    jsonify_rate_limited,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from . import (
    chat_bp,
    cleanup_ephemeral_chats,
    ephemeral_store,
    get_guest_room_ids,
    get_session_id,
    get_temporary_user_store_key,
    register_guest_room,
    unregister_guest_room,
)

logger = logging.getLogger(__name__)

# 日本語: タスク起動メッセージのパーサはロジックを services へ移したが、
#         ブループリント経由で参照している既存の呼び出し元のために別名を残す。
# English: The task-launch parser moved to services; this alias keeps the existing
#          blueprint-level reference working for callers that import it from here.
_parse_task_launch_message = parse_task_launch_message


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
    return f"{id_line}event: {event}\ndata: {body}\n\n".encode()


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
    #
    # 同期イテレータをそのまま渡すと Starlette が `iterate_in_threadpool` で回し、
    # 次のイベントを待つ `next()` が anyio 既定 CapacityLimiter（40トークン）を
    # ハートビート間隔ぶん占有する。進行中の SSE 1本につき1トークンを握り続けるため、
    # 同時ストリームが40本を超えるとワーカー内の `run_in_threadpool` が全て止まる。
    # `iterate_blocking` で SSE 専用プールへ逃がし、共有プールから切り離す。
    # Handing Starlette a sync iterator makes it drive the stream through
    # `iterate_in_threadpool`, where each blocking `next()` holds one of anyio's 40 default
    # capacity tokens for a whole heartbeat interval. Past 40 concurrent streams every
    # `run_in_threadpool` call in the worker stalls, so the iteration is offloaded to the
    # dedicated SSE pool instead.
    return StreamingResponse(
        iterate_blocking(events),
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
    # 依存はリクエストごとに解決する。モジュール属性を差し替えるテストの意図を保つため。
    # Dependencies resolve per request so tests that swap module attributes keep working.
    return ChatPostUseCase(
        ChatPostUseCaseDependencies(
            logger=logger,
            web=ChatPostWebDependencies(
                require_json_dict=require_json_dict,
                validate_payload_model=validate_payload_model,
                jsonify=jsonify,
                jsonify_rate_limited=jsonify_rate_limited,
                jsonify_service_error=jsonify_service_error,
                log_and_internal_server_error=log_and_internal_server_error,
                build_llm_stream_response=_build_llm_stream_response,
                iter_llm_stream_events=_iter_llm_stream_events,
            ),
            rooms=ChatPostRoomDependencies(
                cleanup_ephemeral_chats=cleanup_ephemeral_chats,
                validate_guest_room_access=_validate_guest_room_access,
                resolve_authenticated_room_target=_resolve_authenticated_room_target,
                ensure_ephemeral_room=_ensure_ephemeral_room,
                get_temporary_user_store_key=get_temporary_user_store_key,
                get_session_id=get_session_id,
                ephemeral_store=ephemeral_store,
            ),
            persistence=ChatPostPersistenceDependencies(
                save_message_to_db=save_message_to_db,
                store_user_message_and_load_turn_context=store_user_message_and_load_turn_context,
                get_room_summary=get_room_summary,
                list_room_memory_facts=list_room_memory_facts,
                remember_facts_from_message=remember_facts_from_message,
                rename_chat_room_if_current_title_in=rename_chat_room_if_current_title_in,
                rebuild_room_summary=rebuild_room_summary,
                cleanup_unanswered_user_messages=_cleanup_unanswered_user_messages,
                load_project_context=get_project_context,
            ),
            prompts=ChatPostPromptDependencies(
                normalize_messages_for_llm=normalize_messages_for_llm,
                find_latest_task_launch_request=find_latest_task_launch_request,
                load_task_prompt_data=_load_task_prompt_data,
                build_task_prompt=_build_task_prompt,
                get_user_by_id=get_user_by_id,
                build_user_profile_prompt=_build_user_profile_prompt,
                build_context_messages=build_context_messages,
                build_base_system_prompt=partial(_build_base_system_prompt, locale=locale),
                load_enabled_user_skills=list_enabled_user_skills,
                build_user_skills_prompt=build_enabled_user_skills_prompt,
            ),
            limits=ChatPostLimitDependencies(
                validate_model_name=validate_model_name,
                consume_guest_chat_daily_limit=consume_guest_chat_daily_limit,
                get_seconds_until_tomorrow=get_seconds_until_tomorrow,
                consume_llm_daily_quota=consume_llm_daily_quota,
                get_seconds_until_daily_reset=get_seconds_until_daily_reset,
            ),
            generation=ChatPostGenerationDependencies(
                build_generation_key=build_generation_key,
                has_active_generation=has_active_generation,
                is_streaming_model=is_streaming_model,
                start_generation_job=start_generation_job,
                get_llm_response=get_llm_response,
                decide_generative_ui_mode=decide_generative_ui_mode,
                is_retryable_llm_error=is_retryable_llm_error,
                search_personal_knowledge=search_personal_knowledge_for_tool,
                search_shared_prompts=search_shared_prompts_for_tool,
            ),
            background=ChatPostBackgroundDependencies(
                submit_background_task=submit_background_task,
                should_extract_context=should_extract_context,
                schedule_context_extraction=schedule_context_extraction,
            ),
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


# 日本語: 再生成エンドポイントのログ文言。共有パイプラインへ渡し、既存の文言をそのまま維持する。
# English: Log wording for the regenerate endpoint, passed to the shared pipeline so the
#          existing messages stay byte-for-byte identical.
_REGENERATE_LOG_MESSAGES = ChatRegenerationLogMessages(
    user_profile_load_failed="Failed to load user profile context for regenerate; proceeding without it.",
    room_summary_load_failed="Failed to load room summary for regenerate; proceeding without it.",
    memory_facts_load_failed="Failed to load memory facts for regenerate; proceeding without them.",
    generative_ui_mode_failed=(
        "Failed to decide generative UI mode for regeneration; continuing without intent recovery."
    ),
    room_summary_rebuild_failed="Failed to rebuild room summary after regeneration for %s.",
)

# 日本語: 編集再生成エンドポイントのログ文言。
# English: Log wording for the edit-and-regenerate endpoint.
_EDIT_AND_REGENERATE_LOG_MESSAGES = ChatRegenerationLogMessages(
    user_profile_load_failed="Failed to load user profile for edit_and_regenerate; proceeding without it.",
    room_summary_load_failed="Failed to load room summary for edit_and_regenerate; proceeding without it.",
    memory_facts_load_failed="Failed to load memory facts for edit_and_regenerate; proceeding without them.",
    generative_ui_mode_failed=(
        "Failed to decide generative UI mode for edit_and_regenerate; continuing without intent recovery."
    ),
    room_summary_rebuild_failed="Failed to rebuild room summary after edit_and_regenerate for %s.",
)


# 再生成パイプラインへ渡す依存関係を組み立てるファクトリ関数
# Factory that assembles the dependency bundle handed to the regeneration pipeline.
def _build_regeneration_dependencies() -> ChatRegenerationDependencies:
    """
    再生成パイプラインが使うDB／LLM／一時ストアの境界を、このモジュールの解決済み関数から束ねます。
    Bundles the DB, LLM and ephemeral-store boundaries used by the regeneration pipeline.
    """
    # 依存はリクエストごとに解決する。モジュール属性を差し替えるテストの意図を保つため。
    # Dependencies resolve per request so tests that swap module attributes keep working.
    return ChatRegenerationDependencies(
        logger=logger,
        ephemeral_store=ephemeral_store,
        load_task_prompt_data=_load_task_prompt_data,
        load_project_context_for_room=_load_project_context_for_room,
        list_enabled_user_skills=list_enabled_user_skills,
        get_user_by_id=get_user_by_id,
        get_room_summary=get_room_summary,
        list_room_memory_facts=list_room_memory_facts,
        get_room_web_search_contexts=get_room_web_search_contexts,
        consume_llm_daily_quota=consume_llm_daily_quota,
        is_streaming_model=is_streaming_model,
        search_personal_knowledge=search_personal_knowledge_for_tool,
        search_shared_prompts=search_shared_prompts_for_tool,
        get_llm_response=get_llm_response,
        save_message_to_db=save_message_to_db,
        get_chat_room_messages=get_chat_room_messages,
        rebuild_room_summary=rebuild_room_summary,
        cleanup_unanswered_user_messages=_cleanup_unanswered_user_messages,
    )


# 共有パイプラインの結果を HTTP レスポンスへ変換する関数
# Convert a shared-pipeline outcome into the HTTP response for the endpoint.
def _render_regeneration_outcome(outcome: ChatRegenerationOutcome):
    """
    共有パイプラインの結果をレスポンスへ変換します。レスポンス生成はブループリント側の責務です。
    Renders a shared-pipeline outcome; response construction stays a blueprint concern.
    """
    if isinstance(outcome, ChatRegenerationStreamStarted):
        return _build_llm_stream_response(_iter_llm_stream_events(outcome.job))
    if isinstance(outcome, ChatRegenerationRateLimited):
        return jsonify_rate_limited(outcome.message, retry_after=outcome.retry_after)
    if isinstance(outcome, ChatRegenerationRejected):
        return jsonify(outcome.payload, status_code=outcome.status_code)
    return jsonify(outcome.payload)


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

    # ここから先は編集再生成と同一の処理なので、services 側の単一実装へ委譲する。
    # Everything below is identical to edit-and-regenerate, so it is delegated to the
    # single shared implementation in services/.
    return _render_regeneration_outcome(
        await run_chat_regeneration(
            ChatRegenerationInput(
                dependencies=_build_regeneration_dependencies(),
                log_messages=_REGENERATE_LOG_MESSAGES,
                chat_room_id=chat_room_id,
                model=model,
                user_id=user_id,
                sid=sid,
                room_mode=room_mode,
                all_messages=all_messages,
                assistant_parent_id=assistant_parent_id,
                use_personal_knowledge=use_personal_knowledge,
                use_shared_prompts=use_shared_prompts,
                locale=get_request_locale(request),
                llm_daily_limit_service=resolved_llm_daily_limit_service,
                chat_generation_service=resolved_chat_generation_service,
                # 再生成は新しい発話を受け取らないため、検索クエリは履歴の最新ユーザー発話から導出させる。
                # Regeneration receives no new message, so the lookup query is derived from
                # the latest user message in the history.
                selected_reference_query=None,
                # 再生成はこのリクエストで新しいユーザー発話を保存していないため、
                # 失敗時に掃除する対象がない。掃除すると既存の発話まで消えてしまう。
                # Regeneration saves no new user message, so there is nothing to
                # clean up; running the cleanup would delete an existing message.
                cleanup_unanswered_user_messages_on_error=False,
            )
        )
    )


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

    # ここから先は再生成と同一の処理なので、services 側の単一実装へ委譲する。
    # Everything below is identical to plain regeneration, so it is delegated to the
    # single shared implementation in services/.
    return _render_regeneration_outcome(
        await run_chat_regeneration(
            ChatRegenerationInput(
                dependencies=_build_regeneration_dependencies(),
                log_messages=_EDIT_AND_REGENERATE_LOG_MESSAGES,
                chat_room_id=chat_room_id,
                model=model,
                user_id=user_id,
                sid=sid,
                room_mode=room_mode,
                all_messages=all_messages,
                assistant_parent_id=assistant_parent_id,
                use_personal_knowledge=use_personal_knowledge,
                use_shared_prompts=use_shared_prompts,
                locale=get_request_locale(request),
                llm_daily_limit_service=resolved_llm_daily_limit_service,
                chat_generation_service=resolved_chat_generation_service,
                # 編集再生成は編集後の本文をそのまま参照検索のクエリに使う。
                # Edit-and-regenerate uses the edited body itself as the lookup query.
                selected_reference_query=new_message,
                # 編集再生成はこのリクエストで編集後のユーザー発話を保存しているため、
                # 生成が失敗したら未回答の発話を掃除する。
                # Edit-and-regenerate saved the edited user message in this request, so a
                # failed generation must discard that unanswered message.
                cleanup_unanswered_user_messages_on_error=True,
            )
        )
    )


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

    if user_id is not None:
        try:
            _room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
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

    if user_id is not None:
        try:
            _room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
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

    if user_id is not None:
        try:
            _room_mode, sid, legacy_response = await _resolve_authenticated_room_target(
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
