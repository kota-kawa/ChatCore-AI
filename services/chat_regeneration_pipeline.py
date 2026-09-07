"""
再生成系エンドポイント（chat_regenerate / chat_edit_and_regenerate）が共有する
「メッセージ正規化 → プロンプト構築 → 生成開始」のパイプラインを1箇所に集約します。
Holds the single implementation of the "normalize messages → build prompts → start
generation" pipeline shared by the chat_regenerate and chat_edit_and_regenerate endpoints.

呼び出し側（ブループリント）は各エンドポイント固有の前処理（リクエスト検証、ルーム解決、
履歴の切り詰めや編集）だけを担い、ここへ ChatRegenerationInput を渡します。
The caller (blueprint) keeps only its endpoint-specific preamble (request validation, room
resolution, history truncation or message editing) and hands a ChatRegenerationInput here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from services.async_utils import run_blocking
from services.chat_async_bridge import _run_async_callback
from services.chat_context import build_context_messages
from services.chat_generation import (
    ChatGenerationAlreadyRunningError,
    ChatGenerationJob,
    ChatGenerationService,
    build_generation_key,
    has_active_generation,
    start_generation_job,
)
from services.chat_message_normalization import (
    find_latest_task_launch_request,
    normalize_messages_for_llm,
    prepend_attached_files_to_user_messages,
)
from services.chat_prompt import (
    build_base_system_prompt,
    build_task_prompt,
    build_user_profile_prompt,
)
from services.ephemeral_store import EphemeralChatStore
from services.generative_ui import (
    decide_generative_ui_mode,
    normalize_response_with_artifact_retry,
)
from services.llm import (
    LlmAuthenticationError,
    LlmInvalidModelError,
    LlmRateLimitError,
    LlmServiceError,
)
from services.llm_daily_limit import (
    LlmDailyLimitService,
    get_seconds_until_daily_reset,
)
from services.selected_reference_context import (
    SelectedReferenceLookupTrace,
    augment_messages_with_selected_references_async,
)
from services.selected_reference_sources import build_selected_reference_searchers
from services.user_skills import build_chat_skills_context
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

# 生成中の重複リクエストを弾く際の共通文言（両エンドポイントで同一）
# Shared message returned when a generation is already running (identical for both endpoints).
GENERATION_ALREADY_RUNNING_MESSAGE = "このチャットルームでは回答を生成中です。完了までお待ちください。"


# 依存として差し替える境界（DB／LLM／一時ストア）の型定義
# Typed boundaries injected as dependencies (DB, LLM and ephemeral store access).
class LoadTaskPromptData(Protocol):
    def __call__(
        self,
        task: str,
        user_id: int | None,
        task_id: int | None = None,
    ) -> Awaitable[dict[str, Any] | None]: ...


class LoadProjectContextForRoom(Protocol):
    def __call__(
        self,
        user_id: int | None,
        room_mode: str,
        chat_room_id: str,
    ) -> Awaitable[str | None]: ...


class ConsumeLlmDailyQuota(Protocol):
    def __call__(
        self,
        *,
        service: LlmDailyLimitService | None,
        user_key: str | None,
    ) -> tuple[bool, int, int]: ...


class SaveMessageToDb(Protocol):
    def __call__(
        self,
        chat_room_id: str,
        message: str,
        sender: str,
        attached_file_names: list[str] | None = None,
        parent_id: int | None = None,
        message_parts: list[dict[str, Any]] | None = None,
        attached_file_contents: list[Any] | None = None,
        web_search_context: list[dict[str, Any]] | None = None,
    ) -> Awaitable[int | None]: ...


class RebuildRoomSummary(Protocol):
    def __call__(
        self,
        chat_room_id: str,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
    ) -> Awaitable[str]: ...


class CleanupUnansweredUserMessages(Protocol):
    def __call__(
        self,
        chat_room_id: str,
        *,
        user_id: int | None = None,
        sid: str | None = None,
    ) -> Awaitable[None]: ...


# エンドポイントごとに文言が異なるログメッセージ
# Log messages whose wording differs per endpoint.
@dataclass(frozen=True)
class ChatRegenerationLogMessages:
    """
    共有パイプライン内で出すログの文言です。regenerate と edit_and_regenerate で
    既存の文言が異なるため、まとめ直さずエンドポイントごとの文言をそのまま渡します。
    Wording of the logs emitted inside the shared pipeline. chat_regenerate and
    chat_edit_and_regenerate already word these differently, so each endpoint passes its
    own text instead of the two being merged into one message.
    """

    user_profile_load_failed: str
    room_summary_load_failed: str
    memory_facts_load_failed: str
    generative_ui_mode_failed: str
    room_summary_rebuild_failed: str


# 共有パイプラインが利用する外部境界をまとめた依存オブジェクト
# Dependency object bundling the external boundaries used by the shared pipeline.
@dataclass(frozen=True)
class ChatRegenerationDependencies:
    logger: logging.Logger
    ephemeral_store: EphemeralChatStore
    load_task_prompt_data: LoadTaskPromptData
    load_project_context_for_room: LoadProjectContextForRoom
    list_enabled_user_skills: Callable[[int], Awaitable[Sequence[dict[str, Any]]]]
    get_user_by_id: Callable[[int], Awaitable[dict[str, Any] | None]]
    get_room_summary: Callable[[str], Awaitable[dict[str, Any] | None]]
    list_room_memory_facts: Callable[[str], Awaitable[list[str]]]
    get_room_web_search_contexts: Callable[[str], Awaitable[list[dict[str, Any]]]]
    consume_llm_daily_quota: ConsumeLlmDailyQuota
    is_streaming_model: Callable[[str], bool]
    search_personal_knowledge: Callable[[int, str], Awaitable[dict[str, Any]]]
    search_shared_prompts: Callable[[str], Awaitable[dict[str, Any]]]
    get_llm_response: Callable[[list[dict[str, Any]], str], str | None]
    save_message_to_db: SaveMessageToDb
    get_chat_room_messages: Callable[[str], Awaitable[list[dict[str, Any]]]]
    rebuild_room_summary: RebuildRoomSummary
    cleanup_unanswered_user_messages: CleanupUnansweredUserMessages


# 共有パイプラインの入力（各エンドポイントの前処理が確定させた状態）
# Input to the shared pipeline: the state each endpoint's preamble has already resolved.
@dataclass(frozen=True)
class ChatRegenerationInput:
    dependencies: ChatRegenerationDependencies
    log_messages: ChatRegenerationLogMessages
    chat_room_id: str
    model: str
    user_id: int | None
    sid: str | None
    room_mode: str
    all_messages: list[dict[str, Any]]
    assistant_parent_id: int | None
    use_personal_knowledge: bool
    use_shared_prompts: bool
    locale: str
    llm_daily_limit_service: LlmDailyLimitService | None = None
    chat_generation_service: ChatGenerationService | None = None
    # 日本語: 参照検索のクエリ。chat_edit_and_regenerate は編集後の本文（new_message）を渡し、
    #         chat_regenerate は None を渡して正規化済み履歴の最新ユーザー発話から導出させる。
    # English: Query for the selected-reference lookup. chat_edit_and_regenerate passes the edited
    #          body (new_message); chat_regenerate passes None so it is derived from the latest user
    #          message of the normalized history instead.
    selected_reference_query: str | None = None
    # 日本語: 生成失敗時に未回答のユーザー発話を掃除するか。chat_edit_and_regenerate は
    #         このリクエストで編集後の発話を保存しているため True。chat_regenerate は
    #         新しい発話を保存していないので掃除対象がなく、掃除すると既存の発話まで消える。
    # English: Whether a failed generation should discard the unanswered user message.
    #          chat_edit_and_regenerate saved the edited message in this request, so it is True.
    #          chat_regenerate saves no new user message, so there is nothing to clean up and
    #          running the cleanup would delete an existing message.
    cleanup_unanswered_user_messages_on_error: bool = False


# パイプラインの結果（レスポンス組み立てはブループリント側の責務）
# Pipeline outcomes; turning them into HTTP responses stays a blueprint concern.
@dataclass(frozen=True)
class ChatRegenerationRejected:
    """エラー応答として返すペイロードとステータス / Payload and status for an error response."""

    payload: dict[str, Any]
    status_code: int


@dataclass(frozen=True)
class ChatRegenerationRateLimited:
    """日次上限に達した際のレート制限応答 / Rate-limited response for an exhausted daily quota."""

    message: str
    retry_after: int


@dataclass(frozen=True)
class ChatRegenerationStreamStarted:
    """SSE配信すべきバックグラウンド生成ジョブ / Background generation job to deliver over SSE."""

    job: ChatGenerationJob


@dataclass(frozen=True)
class ChatRegenerationCompleted:
    """非ストリーミング経路で確定した応答ペイロード / Response payload settled by the non-streaming path."""

    payload: dict[str, Any]


ChatRegenerationOutcome = (
    ChatRegenerationRejected
    | ChatRegenerationRateLimited
    | ChatRegenerationStreamStarted
    | ChatRegenerationCompleted
)


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


# メッセージ列から最新のユーザー発話本文を取り出す
# Pick the content of the latest user message from a message list.
def _latest_user_content(messages: list[dict[str, Any]]) -> str:
    return next(
        (
            str(message.get("content") or "")
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )


# 再生成ターンのプロンプトを組み立て、生成を開始（またはエラーを返す）する共有パイプライン
# Shared pipeline that builds the regeneration prompt and starts generation (or returns an error).
async def run_chat_regeneration(pipeline_input: ChatRegenerationInput) -> ChatRegenerationOutcome:
    """
    再生成・編集再生成の両エンドポイントで共通の処理を実行します。
    Runs the pipeline shared by the regenerate and edit-and-regenerate endpoints.
    """
    deps = pipeline_input.dependencies
    logger = deps.logger
    log_messages = pipeline_input.log_messages
    chat_room_id = pipeline_input.chat_room_id
    model = pipeline_input.model
    user_id = pipeline_input.user_id
    sid = pipeline_input.sid
    room_mode = pipeline_input.room_mode
    all_messages = pipeline_input.all_messages
    assistant_parent_id = pipeline_input.assistant_parent_id
    request_locale = pipeline_input.locale

    normalized_all_messages = normalize_messages_for_llm(all_messages)
    # 添付本文を前置する前のテキストを検索クエリに使う（前置後は添付本文が混ざる）。
    # Derive the query before attachments are prepended, so it stays the user's own text.
    selected_reference_query = pipeline_input.selected_reference_query
    if selected_reference_query is None:
        selected_reference_query = _latest_user_content(normalized_all_messages)
    normalized_all_messages = prepend_attached_files_to_user_messages(
        normalized_all_messages
    )
    active_task_request = find_latest_task_launch_request(normalized_all_messages)
    prompt_data = None
    if active_task_request is not None:
        task_id = active_task_request.get("task_id")
        if task_id is None:
            prompt_data = await deps.load_task_prompt_data(active_task_request["task"], user_id)
        else:
            prompt_data = await deps.load_task_prompt_data(active_task_request["task"], user_id, task_id)

    task_prompt = build_task_prompt(prompt_data) if prompt_data else None
    enabled_user_skills: list[dict[str, Any]] = []
    room_summary = ""
    memory_facts: list[str] = []
    user = None
    user_profile_prompt = None

    if user_id is not None:
        try:
            enabled_user_skills = list(await deps.list_enabled_user_skills(user_id))
        except Exception:
            logger.warning("Failed to load enabled user skills; proceeding without them.")
        try:
            user = await deps.get_user_by_id(user_id)
            user_profile_prompt = build_user_profile_prompt(user)
        except Exception:
            logger.warning(log_messages.user_profile_load_failed)

    user_skills_prompt, generative_ui_enabled = build_chat_skills_context(
        enabled_user_skills,
        user,
        locale=request_locale,
    )

    project_instructions = await deps.load_project_context_for_room(
        user_id, room_mode, chat_room_id
    )

    if user_id is not None and room_mode == "normal":
        try:
            summary_payload = await deps.get_room_summary(chat_room_id)
            room_summary = str((summary_payload or {}).get("summary") or "")
        except Exception:
            logger.warning(log_messages.room_summary_load_failed)
        try:
            memory_facts = await deps.list_room_memory_facts(chat_room_id)
        except Exception:
            logger.warning(log_messages.memory_facts_load_failed)

    conversation_messages = build_context_messages(
        base_system_prompt=build_base_system_prompt(locale=request_locale),
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
            await deps.get_room_web_search_contexts(chat_room_id)
        )
    else:
        prior_web_search_results = extract_prior_web_search_results(all_messages)

    generation_key = build_generation_key(chat_room_id=chat_room_id, user_id=user_id, sid=sid)
    if has_active_generation(generation_key, service=pipeline_input.chat_generation_service):
        return ChatRegenerationRejected(
            payload={"error": GENERATION_ALREADY_RUNNING_MESSAGE},
            status_code=409,
        )

    can_access_llm, _, daily_limit = await run_blocking(
        deps.consume_llm_daily_quota,
        service=pipeline_input.llm_daily_limit_service,
        user_key=_build_llm_quota_user_key(user_id, sid),
    )
    if not can_access_llm:
        return ChatRegenerationRateLimited(
            message=(
                f"本日のLLM API利用上限（1ユーザーあたり {daily_limit} 回）に達しました。"
                "日付が変わってから再度お試しください。"
            ),
            retry_after=get_seconds_until_daily_reset(),
        )

    selected_references = build_selected_reference_searchers(
        user_id=user_id,
        use_personal_knowledge=pipeline_input.use_personal_knowledge,
        use_shared_prompts=pipeline_input.use_shared_prompts,
        search_personal_knowledge=deps.search_personal_knowledge,
        search_shared_prompts=deps.search_shared_prompts,
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
            logger.warning(log_messages.generative_ui_mode_failed, exc_info=True)
            ui_mode = None
    else:
        ui_mode = "NONE"

    if deps.is_streaming_model(model):
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
                    lambda: deps.save_message_to_db(
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
                        lambda: deps.get_chat_room_messages(chat_room_id)
                    )
                    _run_async_callback(
                        lambda: deps.rebuild_room_summary(chat_room_id, updated_messages, model=model)
                    )
                except Exception:
                    logger.warning(log_messages.room_summary_rebuild_failed, chat_room_id)
        else:
            persist_response = partial(
                deps.ephemeral_store.append_message,
                sid,
                chat_room_id,
                "assistant",
            )

        # 失敗時の掃除は、このリクエストで新しいユーザー発話を保存したエンドポイントだけが行う。
        # Only the endpoint that saved a new user message in this request cleans up on failure.
        on_error = None
        if pipeline_input.cleanup_unanswered_user_messages_on_error:
            on_error = partial(
                _run_async_callback,
                lambda: deps.cleanup_unanswered_user_messages(
                    chat_room_id,
                    user_id=user_id,
                    sid=sid,
                ),
            )

        try:
            job = start_generation_job(
                generation_key,
                conversation_messages=conversation_messages,
                model=model,
                persist_response=persist_response,
                on_finished=on_finished,
                on_error=on_error,
                service=pipeline_input.chat_generation_service,
                prior_web_search_results=prior_web_search_results,
                personal_knowledge_search=personal_knowledge_search,
                shared_prompt_search=shared_prompt_search,
                selected_reference_trace=selected_reference_trace,
                ui_mode=ui_mode,
            )
        except ChatGenerationAlreadyRunningError:
            return ChatRegenerationRejected(
                payload={"error": GENERATION_ALREADY_RUNNING_MESSAGE},
                status_code=409,
            )

        return ChatRegenerationStreamStarted(job=job)

    # 非ストリーミング再生成でも過去ターンの検索結果を参照用文脈として再注入する
    # Re-inject prior-turn search results for non-streaming regeneration as well.
    conversation_messages = inject_prior_web_search_context(
        conversation_messages, prior_web_search_results
    )

    try:
        bot_reply = await run_blocking(deps.get_llm_response, conversation_messages, model)
    except (LlmInvalidModelError, LlmRateLimitError, LlmAuthenticationError, LlmServiceError) as exc:
        # ユーザーへエラーを返す経路は必ず詳細をログへ残す（例外情報は exception のトレースバックに含まれる）。
        # Always log details on any path that surfaces an error to the user
        # (exception details come from the traceback logger.exception attaches).
        logger.exception(
            "Non-streaming chat generation failed for room %s (model=%s)",
            chat_room_id,
            model,
        )
        return ChatRegenerationRejected(payload={"error": str(exc)}, status_code=500)

    selected_steps = selected_reference_steps(selected_reference_trace)
    if selected_steps:
        trace_block = build_web_search_trace_markdown(
            steps=[*selected_steps, answer_step([])],
        )
        bot_reply = f"{trace_block}\n\n{bot_reply}" if bot_reply else trace_block

    latest_user_message = _latest_user_content(conversation_messages)
    normalized_response = await run_blocking(
        partial(
            normalize_response_with_artifact_retry,
            conversation_messages=conversation_messages,
            model=model,
            generate_response=deps.get_llm_response,
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
        save_args: list[Any] = [
            chat_room_id,
            bot_reply,
            "assistant",
            None,
            assistant_parent_id,
        ]
        if message_parts:
            save_args.append(message_parts)
        await deps.save_message_to_db(*save_args)
    elif sid is not None:
        append_args: list[Any] = [sid, chat_room_id, "assistant", bot_reply]
        if message_parts:
            append_args.append(message_parts)
        await run_blocking(
            deps.ephemeral_store.append_message,
            *append_args,
        )

    response_payload: dict[str, Any] = {"response": bot_reply}
    if message_parts:
        response_payload["parts"] = message_parts
    return ChatRegenerationCompleted(payload=response_payload)
