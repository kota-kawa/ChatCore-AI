from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from fastapi import Request

from services.api_errors import ApiServiceError
from services.attached_files import (
    AttachedFileValidationError,
    format_attached_files_for_prompt,
    prepare_attached_files,
)
from services.async_utils import run_blocking
from services.chat_generation import ChatGenerationAlreadyRunningError
from services.generative_ui import normalize_response_with_artifacts
from services.llm import (
    LlmAuthenticationError,
    LlmInvalidModelError,
    LlmRateLimitError,
    LlmServiceError,
)
from services.request_models import ChatMessageRequest
from services.url_fetcher import extract_urls_from_text, fetch_urls_content
from services.web_search import (
    build_web_search_trace_markdown,
    maybe_augment_messages_with_web_search,
)
from services.chat_title import (
    build_initial_title_candidates,
    maybe_auto_title_chat_room,
)


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
    get_active_leaf_id: Callable[..., Any]
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
    rename_chat_room_if_current_title_in: Callable[..., Any]
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
        attached_files = payload.attached_files or []

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
        should_auto_title_room = False
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

        else:
            sid, guest_error = await deps.validate_guest_room_access(session, chat_room_id)
            if guest_error is not None:
                return guest_error

        try:
            prepared_attached_files = await run_blocking(prepare_attached_files, attached_files)
        except AttachedFileValidationError as exc:
            return deps.jsonify({"error": str(exc)}, status_code=400)

        if "user_id" in session:
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
                attached_file_name_list = [f.name for f in prepared_attached_files] if prepared_attached_files else None
                # New turns extend the active branch: parent is the current branch tip.
                parent_message_id = await run_blocking(deps.get_active_leaf_id, chat_room_id)
                should_auto_title_room = parent_message_id is None
                saved_user_message_id = await run_blocking(
                    deps.save_message_to_db,
                    chat_room_id,
                    formatted_user_message,
                    "user",
                    attached_file_name_list,
                    parent_message_id,
                )
                if should_auto_title_room:
                    all_messages = [{"role": "user", "content": formatted_user_message}]
                else:
                    all_messages = await run_blocking(
                        deps.get_chat_room_messages,
                        chat_room_id,
                    )
        else:
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

        # Build context blocks to prepend to the last user message.
        # Order: fetched URL content → attached file content → user message text.
        prefix_blocks: list[str] = []

        urls_in_message = extract_urls_from_text(user_message)
        if urls_in_message:
            fetched_urls = await run_blocking(fetch_urls_content, urls_in_message)
            if fetched_urls:
                url_xml = "\n".join(
                    f'<url href="{url}">\n{content}\n</url>'
                    for url, content in fetched_urls.items()
                )
                prefix_blocks.append(f"<fetched_urls>\n{url_xml}\n</fetched_urls>")

        if prepared_attached_files:
            prefix_blocks.append(format_attached_files_for_prompt(prepared_attached_files))

        if prefix_blocks and normalized_all_messages and normalized_all_messages[-1].get("role") == "user":
            prefix = "\n\n".join(prefix_blocks)
            last_msg = normalized_all_messages[-1]
            normalized_all_messages = list(normalized_all_messages[:-1]) + [
                {**last_msg, "content": f"{prefix}\n\n{last_msg.get('content', '')}"}
            ]

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
            if not should_auto_title_room:
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

        quota_user_key: str | None
        if user_id is not None:
            quota_user_key = f"user:{user_id}"
        elif sid:
            quota_user_key = f"sid:{sid}"
        else:
            quota_user_key = None
        can_access_llm, _, daily_limit = await run_blocking(
            deps.consume_llm_daily_quota,
            service=llm_daily_limit_service,
            user_key=quota_user_key,
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
                    f"本日のLLM API利用上限（1ユーザーあたり {daily_limit} 回）に達しました。"
                    "日付が変わってから再度お試しください。"
                ),
                retry_after=deps.get_seconds_until_daily_reset(),
            )

        if deps.is_streaming_model(model):
            on_finished = None
            if user_id is not None and room_mode == "normal":

                title_candidates = build_initial_title_candidates(
                    user_message,
                    task_launch_request=active_task_request,
                )

                def persist_response(
                    response: str,
                    *,
                    message_parts: list[dict[str, Any]] | None = None,
                ) -> dict[str, Any] | None:
                    save_args = [
                        chat_room_id,
                        response,
                        "assistant",
                        None,
                        saved_user_message_id,
                    ]
                    if message_parts:
                        save_args.append(message_parts)
                    deps.save_message_to_db(
                        *save_args,
                    )
                    if not should_auto_title_room:
                        return None
                    generated_title = maybe_auto_title_chat_room(
                        chat_room_id=chat_room_id,
                        user_message=user_message,
                        assistant_response=response,
                        model=model,
                        allowed_current_titles=title_candidates,
                        conditional_rename=deps.rename_chat_room_if_current_title_in,
                    )
                    if generated_title:
                        return {"room_title": generated_title}
                    return None

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

        augmentation = maybe_augment_messages_with_web_search(conversation_messages, model)
        response_messages = augmentation.messages

        try:
            bot_reply = await run_blocking(deps.get_llm_response, response_messages, model)
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

        web_search_trace_steps: list[dict[str, str]] = []
        if augmentation.result is not None:
            web_search_trace_steps.extend(
                [
                    {
                        "title": "検索が必要か判断",
                        "detail": "最新情報が必要な可能性を確認しました。",
                    },
                    {
                        "title": f"Web検索: {augmentation.result.query}",
                        "detail": f"{len(augmentation.result.sources)}件の候補を取得しました。",
                    },
                    {
                        "title": "検索結果を確認",
                        "detail": "取得した情報を回答用の文脈に追加しました。",
                    },
                    {
                        "title": "回答を作成",
                        "detail": "検索結果と会話文脈を統合して回答しました。",
                    },
                ]
            )
        trace_block = build_web_search_trace_markdown(
            augmentation.result,
            steps=web_search_trace_steps,
        )
        if trace_block:
            separator = "" if not bot_reply else "\n\n"
            bot_reply = f"{trace_block}{separator}{bot_reply}"

        normalized_response = normalize_response_with_artifacts(bot_reply)
        if normalized_response.validation_errors:
            deps.logger.warning(
                "One or more generated UI artifacts failed validation and were omitted.",
                extra={"validation_errors": normalized_response.validation_errors},
            )
        bot_reply = normalized_response.text
        message_parts = normalized_response.parts

        saved_assistant_message_id: int | None = None
        generated_room_title: str | None = None
        if user_id is not None and room_mode == "normal":
            save_args = [
                chat_room_id,
                bot_reply,
                "assistant",
                None,
                saved_user_message_id,
            ]
            if message_parts:
                save_args.append(message_parts)
            saved_assistant_message_id = await run_blocking(
                deps.save_message_to_db,
                *save_args,
            )
            if should_auto_title_room:
                title_candidates = build_initial_title_candidates(
                    user_message,
                    task_launch_request=active_task_request,
                )
                generated_room_title = await run_blocking(
                    maybe_auto_title_chat_room,
                    chat_room_id=chat_room_id,
                    user_message=user_message,
                    assistant_response=bot_reply,
                    model=model,
                    allowed_current_titles=title_candidates,
                    conditional_rename=deps.rename_chat_room_if_current_title_in,
                )
        else:
            sid = sid or deps.get_session_id(session)
            append_args = [sid, chat_room_id, "assistant", bot_reply]
            if message_parts:
                append_args.append(message_parts)
            await run_blocking(
                deps.ephemeral_store.append_message,
                *append_args,
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

        response_payload = {"response": bot_reply}
        if message_parts:
            response_payload["parts"] = message_parts
        if generated_room_title:
            response_payload["room_title"] = generated_room_title
        return deps.jsonify(response_payload)
