"""
チャット投稿ユースケース（services/chat_use_case.py）が差し替える外部境界を、
関心ごとのグループへ分けて型付けします。
Types the external boundaries injected into the chat-post use case
(services/chat_use_case.py), split into groups by concern.

依存を1枚の巨大なフラット構造にすると、追加のたびに 54 引数の構築箇所を触ることになり、
どのフィールドが何を期待しているのかも読み取れません。ここでは
「Web入出力／セッションとルーム／永続化／プロンプト構築／上限／生成／バックグラウンド」の
7グループへ分割し、各フィールドへ Protocol または引数を明示した Callable を与えます。
A single flat structure forced every new dependency through a 54-argument construction site and
left no way to tell what a field expected. The boundaries are split here into seven groups
(web I/O, session and room access, persistence, prompt building, limits, generation, background
work), and every field carries either a Protocol or a fully parameterised Callable.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, fields
from typing import Any, Protocol, TypeVar

from fastapi import Request
from pydantic import BaseModel
from starlette.responses import Response

from services.api_errors import ApiServiceError
from services.auth_limits import AuthLimitService
from services.chat_generation import ChatGenerationJob, ChatGenerationService
from services.chat_regeneration_pipeline import (
    CleanupUnansweredUserMessages,
    ConsumeLlmDailyQuota,
    LoadTaskPromptData,
    RebuildRoomSummary,
    SaveMessageToDb,
)
from services.ephemeral_store import EphemeralChatStore
from services.generative_ui import GenerativeUiMode
from services.selected_reference_context import SelectedReferenceLookupTrace
from services.user_skills import build_enabled_user_skills_prompt
from services.web_search import WebSearchResult

_ModelT = TypeVar("_ModelT", bound=BaseModel)

# 日本語: 本番の実装は async だが、単体テストは同期の代役を渡す。ユースケース側の
#         _maybe_await が両方を受けるため、その事実をそのまま型で表す。
# English: Production implementations are async while focused unit doubles stay synchronous.
#          The use case funnels these through _maybe_await, so the type says both are accepted.
type MaybeAwaitable[T] = Awaitable[T] | T

# 日本語: ルーム所有権の解決結果（room_mode, 一時ストアキー, 早期返却レスポンス）。
# English: Result of resolving room ownership: room_mode, ephemeral store key, early response.
type RoomTargetResult = tuple[str | None, str | None, Response | None]


# ---------------------------------------------------------------------------
# Web入出力の境界 / Web I/O boundaries
# ---------------------------------------------------------------------------
class RequireJsonDict(Protocol):
    def __call__(self, request: Request) -> Awaitable[tuple[dict[str, Any] | None, Response | None]]: ...


class ValidatePayloadModel(Protocol):
    def __call__(
        self,
        data: dict[str, Any],
        model_class: type[_ModelT],
        *,
        error_message: str,
    ) -> tuple[_ModelT | None, Response | None]: ...


class Jsonify(Protocol):
    def __call__(self, payload: Any, status_code: int = 200) -> Response: ...


class JsonifyRateLimited(Protocol):
    def __call__(self, message: str, *, retry_after: int | None) -> Response: ...


class LogAndInternalServerError(Protocol):
    def __call__(self, logger: logging.Logger, context: str) -> Response: ...


# ---------------------------------------------------------------------------
# セッションとルームアクセスの境界 / Session and room-access boundaries
# ---------------------------------------------------------------------------
class ValidateGuestRoomAccess(Protocol):
    def __call__(
        self,
        session: dict[str, Any],
        chat_room_id: str,
    ) -> Awaitable[tuple[str | None, Response | None]]: ...


class ResolveAuthenticatedRoomTarget(Protocol):
    def __call__(
        self,
        chat_room_id: str,
        user_id: int,
        forbidden_message: str,
    ) -> MaybeAwaitable[RoomTargetResult]: ...


# ---------------------------------------------------------------------------
# 永続化の境界 / Persistence boundaries
# ---------------------------------------------------------------------------
class StoreUserMessageAndLoadTurnContext(Protocol):
    # 日本語: 1投稿ぶんの保存と文脈読み出しを1トランザクションへまとめた境界。
    #         返り値は message_id / parent_message_id / is_first_turn / messages /
    #         web_search_contexts を持つ辞書。
    # English: One boundary that persists the turn and reads its context in a single
    #          transaction, returning message_id, parent_message_id, is_first_turn,
    #          messages and web_search_contexts.
    def __call__(
        self,
        chat_room_id: str,
        message: str,
        sender: str = "user",
        attached_file_names: list[str] | None = None,
        message_parts: list[dict[str, Any]] | None = None,
        attached_file_contents: list[Any] | None = None,
    ) -> MaybeAwaitable[dict[str, Any]]: ...


class RememberFactsFromMessage(Protocol):
    def __call__(
        self,
        chat_room_id: str,
        user_id: int,
        message: str,
        *,
        source_message_id: int | None = None,
    ) -> Awaitable[list[str]]: ...


class RenameChatRoomIfCurrentTitleIn(Protocol):
    def __call__(
        self,
        room_id: str,
        new_title: str,
        allowed_current_titles: list[str],
    ) -> MaybeAwaitable[bool]: ...


# ---------------------------------------------------------------------------
# プロンプト構築の境界 / Prompt-building boundaries
# ---------------------------------------------------------------------------
class BuildContextMessages(Protocol):
    def __call__(
        self,
        *,
        base_system_prompt: str,
        user_profile_prompt: str | None,
        task_prompt: str | None,
        room_summary: str,
        memory_facts: list[str],
        recent_messages: list[dict[str, Any]],
        project_instructions: str | None = None,
        user_skills_prompt: str | None = None,
        generative_ui_enabled: bool = True,
    ) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# 上限判定の境界 / Limit boundaries
# ---------------------------------------------------------------------------
class ConsumeGuestChatDailyLimit(Protocol):
    def __call__(
        self,
        request: Request,
        *,
        service: AuthLimitService | None = None,
    ) -> tuple[bool, str | None]: ...


# ---------------------------------------------------------------------------
# 生成の境界 / Generation boundaries
# ---------------------------------------------------------------------------
class BuildGenerationKey(Protocol):
    def __call__(
        self,
        *,
        chat_room_id: str,
        user_id: int | None = None,
        sid: str | None = None,
    ) -> str: ...


class HasActiveGeneration(Protocol):
    def __call__(
        self,
        job_key: str,
        *,
        service: ChatGenerationService | None = None,
    ) -> bool: ...


class StartGenerationJob(Protocol):
    def __call__(
        self,
        job_key: str,
        *,
        conversation_messages: list[dict[str, Any]],
        model: str,
        # 日本語: persist_response だけは呼び出し側で形が変わる（通常ルームは
        #         message_parts / web_search_context を受ける自前の関数、一時ルームは
        #         EphemeralChatStore.append_message の partial）。ここは本番の
        #         start_generation_job と同じく可変シグネチャのままにする。
        # English: persist_response is the one collaborator whose shape varies per call site
        #          (a bespoke callback taking message_parts/web_search_context for normal rooms,
        #          a partial of EphemeralChatStore.append_message for temporary ones), so it
        #          stays variadic exactly as production start_generation_job declares it.
        persist_response: Callable[..., dict[str, Any] | None],
        on_finished: Callable[[], None] | None = None,
        on_error: Callable[[], None] | None = None,
        service: ChatGenerationService | None = None,
        prior_web_search_results: list[WebSearchResult] | None = None,
        personal_knowledge_search: Callable[[str], dict[str, Any]] | None = None,
        shared_prompt_search: Callable[[str], dict[str, Any]] | None = None,
        selected_reference_trace: list[SelectedReferenceLookupTrace] | None = None,
        ui_mode: GenerativeUiMode | str | None = None,
    ) -> ChatGenerationJob: ...


class DecideGenerativeUiMode(Protocol):
    def __call__(
        self,
        conversation_messages: list[dict[str, Any]],
        model: str,
    ) -> GenerativeUiMode | None: ...


# ---------------------------------------------------------------------------
# バックグラウンド処理の境界 / Background-work boundaries
# ---------------------------------------------------------------------------
class SubmitBackgroundTask(Protocol):
    # 日本語: 第1引数の関数をそのまま実行器へ渡す薄いラッパなので、追加引数は可変で受ける。
    #         テストが args[0] を検査するため、関数は必ず位置引数で渡す。
    # English: A thin wrapper handing its first argument to the executor, so trailing arguments
    #          stay variadic. The task itself is always positional because tests inspect args[0].
    def __call__(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any: ...


class ScheduleContextExtraction(Protocol):
    def __call__(
        self,
        user_id: int,
        *,
        room_id: str,
        assistant_message_id: int,
        user_message: str,
        assistant_response: str,
        locale: Any = None,
    ) -> None: ...


# ---------------------------------------------------------------------------
# 関心ごとに束ねた依存グループ / Dependency groups, bundled by concern
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ChatPostWebDependencies:
    """リクエストのパースとレスポンス生成 / Request parsing and response construction."""

    require_json_dict: RequireJsonDict
    validate_payload_model: ValidatePayloadModel
    jsonify: Jsonify
    jsonify_rate_limited: JsonifyRateLimited
    jsonify_service_error: Callable[[ApiServiceError], Response]
    log_and_internal_server_error: LogAndInternalServerError
    build_llm_stream_response: Callable[[Iterator[bytes]], Response]
    iter_llm_stream_events: Callable[[ChatGenerationJob], Iterator[bytes]]


@dataclass(frozen=True)
class ChatPostRoomDependencies:
    """セッション・ルーム所有権・一時ストア / Session, room ownership and ephemeral store."""

    cleanup_ephemeral_chats: Callable[[], None]
    validate_guest_room_access: ValidateGuestRoomAccess
    resolve_authenticated_room_target: ResolveAuthenticatedRoomTarget
    ensure_ephemeral_room: Callable[[str, str], None]
    get_temporary_user_store_key: Callable[[int], str]
    get_session_id: Callable[[dict[str, Any]], str]
    ephemeral_store: EphemeralChatStore


@dataclass(frozen=True)
class ChatPostPersistenceDependencies:
    """メッセージ・要約・記憶のDB境界 / DB boundaries for messages, summaries and memory."""

    save_message_to_db: SaveMessageToDb
    # 日本語: 発話の保存と、そのターンに要る文脈（履歴・過去の検索結果）の読み出しは
    #         1回のルームツリー読み出しで賄う。個別の get_active_leaf_id /
    #         get_chat_room_messages / get_room_web_search_contexts は同じ木を
    #         3回読んでいたため、この境界へ統合した。
    # English: Persisting the turn and loading the context it needs share one room-tree read.
    #          The separate get_active_leaf_id / get_chat_room_messages /
    #          get_room_web_search_contexts boundaries each re-read the same tree.
    store_user_message_and_load_turn_context: StoreUserMessageAndLoadTurnContext
    get_room_summary: Callable[[str], MaybeAwaitable[dict[str, Any] | None]]
    list_room_memory_facts: Callable[[str], MaybeAwaitable[list[str]]]
    remember_facts_from_message: RememberFactsFromMessage
    rename_chat_room_if_current_title_in: RenameChatRoomIfCurrentTitleIn
    rebuild_room_summary: RebuildRoomSummary
    cleanup_unanswered_user_messages: CleanupUnansweredUserMessages
    load_project_context: Callable[[str], MaybeAwaitable[dict[str, Any] | None]]


@dataclass(frozen=True)
class ChatPostPromptDependencies:
    """会話文脈とシステムプロンプトの組み立て / Assembling conversation context and prompts."""

    normalize_messages_for_llm: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    find_latest_task_launch_request: Callable[[list[dict[str, Any]]], dict[str, Any] | None]
    load_task_prompt_data: LoadTaskPromptData
    build_task_prompt: Callable[[dict[str, Any]], str | None]
    get_user_by_id: Callable[[int], MaybeAwaitable[dict[str, Any] | None]]
    build_user_profile_prompt: Callable[[dict[str, Any] | None], str | None]
    build_context_messages: BuildContextMessages
    build_base_system_prompt: Callable[[], str]
    # 日本語: 絞り込んだ単体テストの代役が構築を続けられるよう、既定値のあるフィールドは末尾へ置く。
    # English: Fields with defaults stay last so focused unit-test doubles keep constructing.
    load_enabled_user_skills: Callable[[int], MaybeAwaitable[Sequence[dict[str, Any]] | None]] | None = None
    build_user_skills_prompt: Callable[[list[dict[str, Any]]], str | None] = build_enabled_user_skills_prompt


@dataclass(frozen=True)
class ChatPostLimitDependencies:
    """ゲスト上限とLLM日次クォータ / Guest limits and the daily LLM quota."""

    validate_model_name: Callable[[str], None]
    consume_guest_chat_daily_limit: ConsumeGuestChatDailyLimit
    get_seconds_until_tomorrow: Callable[[], int]
    consume_llm_daily_quota: ConsumeLlmDailyQuota
    get_seconds_until_daily_reset: Callable[[], int]


@dataclass(frozen=True)
class ChatPostGenerationDependencies:
    """LLM呼び出し・ストリーミングジョブ・参照検索 / LLM calls, streaming jobs and lookups."""

    build_generation_key: BuildGenerationKey
    has_active_generation: HasActiveGeneration
    is_streaming_model: Callable[[str], bool]
    start_generation_job: StartGenerationJob
    get_llm_response: Callable[[list[dict[str, Any]], str], str | None]
    decide_generative_ui_mode: DecideGenerativeUiMode
    is_retryable_llm_error: Callable[[BaseException], bool]
    search_personal_knowledge: Callable[[int, str], Awaitable[dict[str, Any]]]
    search_shared_prompts: Callable[[str], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ChatPostBackgroundDependencies:
    """応答経路から外して実行する処理 / Work deliberately kept off the response path."""

    submit_background_task: SubmitBackgroundTask
    should_extract_context: Callable[[int], MaybeAwaitable[bool]]
    schedule_context_extraction: ScheduleContextExtraction


# 日本語: グループのフィールド名。フラット引数の振り分けと属性委譲の両方で使う。
# English: Group field names, used both for routing flat arguments and for attribute delegation.
_DEPENDENCY_GROUPS: dict[str, type] = {
    "web": ChatPostWebDependencies,
    "rooms": ChatPostRoomDependencies,
    "persistence": ChatPostPersistenceDependencies,
    "prompts": ChatPostPromptDependencies,
    "limits": ChatPostLimitDependencies,
    "generation": ChatPostGenerationDependencies,
    "background": ChatPostBackgroundDependencies,
}


# 日本語: グループの型からフィールド名集合を一度だけ取り出してキャッシュする。
# English: Resolve and cache the field-name set of a group type once.
_GROUP_FIELD_NAMES: dict[str, frozenset[str]] = {
    group_name: frozenset(field.name for field in fields(group_type))
    for group_name, group_type in _DEPENDENCY_GROUPS.items()
}


# 投稿時のチャット処理で使用する外部モジュールやリポジトリの依存関係を集約したクラス
# A class aggregating external dependencies and repositories utilized in chat posting
@dataclass(frozen=True, init=False)
class ChatPostUseCaseDependencies:
    """
    7つの依存グループとロガーだけを持つ最上位の依存オブジェクトです。依存を1つ増やすときは
    該当グループのみを触れば済み、呼び出し側の構築コードは影響を受けません。
    Top-level dependency object holding just the seven groups plus the logger. Adding one
    dependency now means editing a single group instead of every construction site.
    """

    logger: logging.Logger
    web: ChatPostWebDependencies
    rooms: ChatPostRoomDependencies
    persistence: ChatPostPersistenceDependencies
    prompts: ChatPostPromptDependencies
    limits: ChatPostLimitDependencies
    generation: ChatPostGenerationDependencies
    background: ChatPostBackgroundDependencies

    def __init__(
        self,
        *,
        logger: logging.Logger,
        web: ChatPostWebDependencies | None = None,
        rooms: ChatPostRoomDependencies | None = None,
        persistence: ChatPostPersistenceDependencies | None = None,
        prompts: ChatPostPromptDependencies | None = None,
        limits: ChatPostLimitDependencies | None = None,
        generation: ChatPostGenerationDependencies | None = None,
        background: ChatPostBackgroundDependencies | None = None,
        **flat_dependencies: Any,
    ) -> None:
        """
        グループを直接受け取るのが本来の経路です。加えて、個々の依存をフラットなキーワード引数で
        渡す旧来の書き方も受け付け、名前が一致するグループへ振り分けます（既存の単体テストが
        この形で構築しており、テストは変更しない方針のため互換経路として残しています）。
        Groups are the intended input. Individual dependencies may also arrive as flat keyword
        arguments, which are routed into the group that declares each name; the existing unit
        tests construct dependencies that way and are intentionally left untouched.
        """
        provided_groups: dict[str, Any] = {
            "web": web,
            "rooms": rooms,
            "persistence": persistence,
            "prompts": prompts,
            "limits": limits,
            "generation": generation,
            "background": background,
        }
        unrouted = dict(flat_dependencies)
        for group_name, group_type in _DEPENDENCY_GROUPS.items():
            group = provided_groups[group_name]
            if group is None:
                field_names = _GROUP_FIELD_NAMES[group_name]
                group = group_type(
                    **{name: unrouted.pop(name) for name in list(unrouted) if name in field_names}
                )
            object.__setattr__(self, group_name, group)
        if unrouted:
            unexpected = ", ".join(sorted(unrouted))
            raise TypeError(f"Unknown chat post dependencies: {unexpected}")
        object.__setattr__(self, "logger", logger)

    def __getattr__(self, name: str) -> Any:
        """
        グループ化前のフラットな属性名でも読めるようにします。旧来の呼び出し側（単体テスト）が
        deps.get_room_summary のように参照するため、該当グループへ委譲します。
        Resolves the pre-grouping flat attribute names by delegating to the owning group, since
        legacy callers (the unit tests) still read dependencies as deps.get_room_summary.
        """
        if name.startswith("__"):
            raise AttributeError(name)
        state = object.__getattribute__(self, "__dict__")
        for group_name, field_names in _GROUP_FIELD_NAMES.items():
            if name not in field_names:
                continue
            group = state.get(group_name)
            if group is not None:
                return getattr(group, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
