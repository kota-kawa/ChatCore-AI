from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from fastapi import Request

from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.chat_generation import ChatGenerationAlreadyRunningError
from services.llm import (
    LlmAuthenticationError,
    LlmInvalidModelError,
    LlmRateLimitError,
    LlmServiceError,
)
from services.request_models import ChatMessageRequest


@dataclass(frozen=True)
class ChatPostUseCaseDependencies:
    cleanup_ephemeral_chats: Callable[[], Any]
    require_json_dict: Callable[..., Any]
    validate_payload_model: Callable[..., Any]
    jsonify: Callable[..., Any]
    jsonify_rate_limited: Callable[..., Any]
    jsonify_service_error: Callable[..., Any]
    log_and_internal_server_error: Callable[..., Any]
    validate_model_name: Callable[[str], Any]
    consume_guest_chat_daily_limit: Callable[..., Any]
    get_seconds_until_tomorrow: Callable[[], int]
    validate_guest_room_access: Callable[..., Any]
    resolve_authenticated_room_target: Callable[..., Any]
    ensure_ephemeral_room: Callable[..., Any]
    get_temporary_user_store_key: Callable[[int], str]
    ephemeral_store: Any
    save_message_to_db: Callable[..., Any]
    get_chat_room_messages: Callable[..., Any]
    normalize_messages_for_llm: Callable[..., Any]
    find_latest_task_launch_request: Callable[..., Any]
    load_task_prompt_data: Callable[..., Any]
    build_task_prompt: Callable[..., Any]
    get_user_by_id: Callable[..., Any]
    build_user_profile_prompt: Callable[..., Any]
    get_room_summary: Callable[..., Any]
    list_room_memory_facts: Callable[..., Any]
    remember_facts_from_message: Callable[..., Any]
    build_context_messages: Callable[..., Any]
    build_base_system_prompt: Callable[..., Any]
    build_generation_key: Callable[..., Any]
    has_active_generation: Callable[..., Any]
    consume_llm_daily_quota: Callable[..., Any]
    cleanup_failed_room_without_assistant_response: Callable[..., Any]
    get_seconds_until_daily_reset: Callable[[], int]
    is_streaming_model: Callable[[str], bool]
    start_generation_job: Callable[..., Any]
    build_llm_stream_response: Callable[..., Any]
    iter_llm_stream_events: Callable[..., Any]
    get_llm_response: Callable[..., Any]
    is_retryable_llm_error: Callable[[BaseException], bool]
    rebuild_room_summary: Callable[..., Any]
    get_session_id: Callable[[dict], str]
    logger: Any


class ChatPostUseCase:
    def __init__(
        self,
        dependencies: ChatPostUseCaseDependencies,
        *,
        default_model: str,
    ) -> None:
        self.deps = dependencies
        self.default_model = default_model

    async def execute(
        self,
        request: Request,
        *,
        auth_limit_service: Any,
        llm_daily_limit_service: Any,
        chat_generation_service: Any,
    ) -> Any:
        deps = self.deps

        await run_blocking(deps.cleanup_ephemeral_chats)
        data, error_response = await deps.require_json_dict(request)
        if error_response is not None:
            return error_response

        payload, validation_error = deps.validate_payload_model(
            data,
            ChatMessageRequest,
            error_message="'message' が必要です。",
        )
        if validation_error is not None:
            return validation_error

        user_message = payload.message
        chat_room_id = payload.chat_room_id
        model = payload.model or self.default_model

        try:
            deps.validate_model_name(model)
        except LlmInvalidModelError as exc:
            return deps.jsonify({"error": str(exc)}, status_code=400)

        session = request.session
        if "user_id" not in session:
            allowed, message = await run_blocking(
                deps.consume_guest_chat_daily_limit,
                request,
                service=auth_limit_service,
            )
            if not allowed:
                return deps.jsonify_rate_limited(
                    message or "1日10回までです",
                    retry_after=deps.get_seconds_until_tomorrow(),
                )

        sid = None
        room_mode = "temporary"
        user_id = session.get("user_id")
        saved_user_message_id: int | None = None
        formatted_user_message = html.escape(user_message).replace("\n", "<br>")

        if "user_id" in session:
            try:
                room_mode, sid, legacy_response = await run_blocking(
                    deps.resolve_authenticated_room_target,
                    chat_room_id,
                    user_id,
                    "他ユーザーのチャットルームには投稿できません",
                )
                if legacy_response is not None:
                    return legacy_response
            except ApiServiceError as exc:
                return deps.jsonify_service_error(exc)
            except Exception:
                return deps.log_and_internal_server_error(
                    deps.logger,
                    "Failed to validate chat room ownership before posting.",
                )

            if room_mode == "temporary":
                sid = deps.get_temporary_user_store_key(user_id)
                await run_blocking(deps.ensure_ephemeral_room, sid, chat_room_id)
                await run_blocking(
                    deps.ephemeral_store.append_message,
                    sid,
                    chat_room_id,
                    "user",
                    formatted_user_message,
                )
                all_messages = await run_blocking(
                    deps.ephemeral_store.get_messages,
                    sid,
                    chat_room_id,
                )
            else:
                saved_user_message_id = await run_blocking(
                    deps.save_message_to_db,
                    chat_room_id,
                    formatted_user_message,
                    "user",
                )
                all_messages = await run_blocking(deps.get_chat_room_messages, chat_room_id)
        else:
            sid, guest_error = await deps.validate_guest_room_access(session, chat_room_id)
            if guest_error is not None:
                return guest_error

            await run_blocking(
                deps.ephemeral_store.append_message,
                sid,
                chat_room_id,
                "user",
                formatted_user_message,
            )
            all_messages = await run_blocking(
                deps.ephemeral_store.get_messages,
                sid,
                chat_room_id,
            )

        normalized_all_messages = deps.normalize_messages_for_llm(all_messages)
        active_task_request = deps.find_latest_task_launch_request(normalized_all_messages)
        prompt_data = None
        if active_task_request is not None:
            prompt_data = await deps.load_task_prompt_data(active_task_request["task"], user_id)

        task_prompt = deps.build_task_prompt(prompt_data) if prompt_data else None
        room_summary = ""
        memory_facts: list[str] = []
        user_profile_prompt = None

        if user_id is not None:
            try:
                user = await run_blocking(deps.get_user_by_id, user_id)
                user_profile_prompt = deps.build_user_profile_prompt(user)
            except Exception:
                deps.logger.warning("Failed to load user profile context; proceeding without it.")

        if user_id is not None and room_mode == "normal":
            try:
                summary_payload = await run_blocking(deps.get_room_summary, chat_room_id)
                room_summary = str((summary_payload or {}).get("summary") or "")
            except Exception:
                deps.logger.warning("Failed to load room summary; proceeding without it.")
            try:
                memory_facts = await run_blocking(deps.list_room_memory_facts, chat_room_id)
            except Exception:
                deps.logger.warning("Failed to load memory facts; proceeding without them.")
            if saved_user_message_id is not None:
                try:
                    remembered_facts = await run_blocking(
                        deps.remember_facts_from_message,
                        chat_room_id,
                        user_id,
                        user_message,
                        source_message_id=saved_user_message_id,
                    )
                    for fact in remembered_facts:
                        if fact not in memory_facts:
                            memory_facts.insert(0, fact)
                except Exception:
                    deps.logger.warning(
                        "Failed to update memory facts for chat room %s.",
                        chat_room_id,
                    )

        conversation_messages = deps.build_context_messages(
            base_system_prompt=deps.build_base_system_prompt(),
            user_profile_prompt=user_profile_prompt,
            task_prompt=task_prompt,
            room_summary=room_summary,
            memory_facts=memory_facts,
            recent_messages=normalized_all_messages,
        )

        generation_key = deps.build_generation_key(
            chat_room_id=chat_room_id,
            user_id=user_id,
            sid=sid,
        )
        if deps.has_active_generation(generation_key, service=chat_generation_service):
            return deps.jsonify(
                {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
                status_code=409,
            )

        can_access_llm, _, daily_limit = await run_blocking(
            deps.consume_llm_daily_quota,
            service=llm_daily_limit_service,
        )
        if not can_access_llm:
            await run_blocking(
                deps.cleanup_failed_room_without_assistant_response,
                chat_room_id,
                user_id=user_id,
                sid=sid,
            )
            return deps.jsonify_rate_limited(
                (
                    f"本日のLLM API利用上限（全ユーザー合計 {daily_limit} 回）に達しました。"
                    "日付が変わってから再度お試しください。"
                ),
                retry_after=deps.get_seconds_until_daily_reset(),
            )

        if deps.is_streaming_model(model):
            on_finished = None
            if user_id is not None and room_mode == "normal":

                def persist_response(response: str) -> None:
                    deps.save_message_to_db(chat_room_id, response, "assistant")

                def on_finished() -> None:
                    try:
                        updated_messages = deps.get_chat_room_messages(chat_room_id)
                        deps.rebuild_room_summary(chat_room_id, updated_messages)
                    except Exception:
                        deps.logger.warning(
                            "Failed to rebuild room summary after streaming response for %s.",
                            chat_room_id,
                        )
            else:
                persist_response = partial(
                    deps.ephemeral_store.append_message,
                    sid,
                    chat_room_id,
                    "assistant",
                )

            try:
                job = deps.start_generation_job(
                    generation_key,
                    conversation_messages=conversation_messages,
                    model=model,
                    persist_response=persist_response,
                    on_finished=on_finished,
                    on_error=partial(
                        deps.cleanup_failed_room_without_assistant_response,
                        chat_room_id,
                        user_id=user_id,
                        sid=sid,
                    ),
                    service=chat_generation_service,
                )
            except ChatGenerationAlreadyRunningError:
                return deps.jsonify(
                    {"error": "このチャットルームでは回答を生成中です。完了までお待ちください。"},
                    status_code=409,
                )

            return deps.build_llm_stream_response(deps.iter_llm_stream_events(job))

        try:
            bot_reply = await run_blocking(deps.get_llm_response, conversation_messages, model)
        except LlmInvalidModelError as exc:
            await run_blocking(
                deps.cleanup_failed_room_without_assistant_response,
                chat_room_id,
                user_id=user_id,
                sid=sid,
            )
            return deps.jsonify({"error": str(exc)}, status_code=400)
        except LlmRateLimitError as exc:
            await run_blocking(
                deps.cleanup_failed_room_without_assistant_response,
                chat_room_id,
                user_id=user_id,
                sid=sid,
            )
            return deps.jsonify_rate_limited(
                "AI提供元が混み合っています。時間をおいて再試行してください。",
                retry_after=(
                    exc.retry_after_seconds
                    if exc.retry_after_seconds is not None
                    else 10
                ),
            )
        except LlmAuthenticationError:
            deps.logger.exception(
                "LLM authentication/configuration error while generating chat response."
            )
            await run_blocking(
                deps.cleanup_failed_room_without_assistant_response,
                chat_room_id,
                user_id=user_id,
                sid=sid,
            )
            return deps.jsonify(
                {"error": "AI設定エラーが発生しました。管理者に連絡してください。"},
                status_code=502,
            )
        except LlmServiceError as exc:
            retryable = deps.is_retryable_llm_error(exc)
            deps.logger.exception(
                "Failed to get LLM response (retryable=%s).",
                retryable,
            )
            await run_blocking(
                deps.cleanup_failed_room_without_assistant_response,
                chat_room_id,
                user_id=user_id,
                sid=sid,
            )
            return deps.jsonify(
                {
                    "error": "AI応答の生成に失敗しました。時間をおいて再試行してください。",
                    "retryable": retryable,
                },
                status_code=502,
            )

        saved_assistant_message_id: int | None = None
        if user_id is not None and room_mode == "normal":
            saved_assistant_message_id = await run_blocking(
                deps.save_message_to_db,
                chat_room_id,
                bot_reply,
                "assistant",
            )
        else:
            sid = sid or deps.get_session_id(session)
            await run_blocking(
                deps.ephemeral_store.append_message,
                sid,
                chat_room_id,
                "assistant",
                bot_reply,
            )

        if (
            user_id is not None
            and room_mode == "normal"
            and saved_assistant_message_id is not None
        ):
            try:
                all_messages = await run_blocking(deps.get_chat_room_messages, chat_room_id)
                await run_blocking(deps.rebuild_room_summary, chat_room_id, all_messages)
            except Exception:
                deps.logger.warning(
                    "Failed to rebuild room summary for chat room %s.",
                    chat_room_id,
                )

        return deps.jsonify({"response": bot_reply})
