"""
チャット投稿エンドポイント（POST /api/chat）のユースケースです。
Use case behind the chat post endpoint (POST /api/chat).

execute() は各フェーズを順に呼ぶオーケストレーターに留め、実処理はフェーズごとの
プライベートメソッドへ分けています。1リクエストの間だけ引き回す状態は _ChatPostTurn に集約します。
execute() stays an orchestrator that calls one phase after another; the work itself lives in a
private method per phase. State carried across a single request is bundled in _ChatPostTurn.
"""

from __future__ import annotations

import asyncio
import html
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from fastapi import Request
from starlette.responses import Response

from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.attached_files import (
    AttachedFileValidationError,
    PreparedAttachedFile,
    decode_attached_files_from_storage,
    format_attached_files_for_prompt,
    prepare_attached_files,
)
from services.auth_limits import AuthLimitService
from services.chat_async_bridge import _run_async_callback
from services.chat_generation import ChatGenerationAlreadyRunningError, ChatGenerationService
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
from services.chat_title import build_initial_title_candidates, generate_chat_room_title
from services.error_messages import ERROR_CHAT_EMPTY_RESPONSE
from services.generative_ui import GenerativeUiMode, normalize_response_with_artifact_retry
from services.llm import (
    LlmAuthenticationError,
    LlmInvalidModelError,
    LlmRateLimitError,
    LlmServiceError,
)
from services.llm_daily_limit import LlmDailyLimitService
from services.message_parts_display import normalize_message_parts_for_display
from services.request_models import ChatMessageRequest
from services.selected_reference_context import (
    SelectedReferenceLookupTrace,
    augment_messages_with_selected_references_async,
)
from services.selected_reference_sources import build_selected_reference_searchers
from services.url_fetcher import extract_urls_from_text, fetch_urls_content
from services.user_skills import build_chat_skills_context
from services.web_search import (
    WebSearchResult,
    combine_web_search_results,
    deserialize_web_search_results,
    extract_prior_web_search_results,
    inject_prior_web_search_context,
    resolve_web_search_citations,
    strip_web_search_citation_html,
)
from services.web_search_trace import (
    TraceStep,
    answer_step,
    build_web_search_trace_markdown,
    selected_reference_steps,
)

# 日本語: 依存グループはこのモジュール経由でも参照されてきたため、再エクスポートを維持する。
# English: The dependency groups have always been reachable through this module, so they are re-exported.
__all__ = [
    "ChatPostBackgroundDependencies",
    "ChatPostGenerationDependencies",
    "ChatPostLimitDependencies",
    "ChatPostPersistenceDependencies",
    "ChatPostPromptDependencies",
    "ChatPostRoomDependencies",
    "ChatPostUseCase",
    "ChatPostUseCaseDependencies",
    "ChatPostWebDependencies",
]

# 生成中の重複リクエストを弾く際の文言
# Message returned when a generation is already running for the room.
_GENERATION_ALREADY_RUNNING_MESSAGE = "このチャットルームでは回答を生成中です。完了までお待ちください。"


async def _maybe_await(value: Any) -> Any:
    """Accept async production dependencies while keeping light unit doubles usable."""
    return await value if inspect.isawaitable(value) else value


def _messages_including_reply(history: list[dict[str, Any]], reply: str) -> list[dict[str, Any]]:
    """
    このターンの履歴に保存済みの応答を足した一覧を返します。要約の入力はこれで確定するため、
    ルーム全体を読み直す必要はありません。
    Return this turn's history with the persisted reply appended. That is the whole summary input,
    so the room does not have to be read back out of the database.
    """
    return [*history, {"role": "assistant", "content": reply}]


# 1リクエストの処理中だけ受け渡す作業状態
# Working state carried across the phases of a single request
@dataclass
class _ChatPostTurn:
    """
    execute() の各フェーズが読み書きする、このターン限りの状態です。フェーズ間で
    十数個のローカル変数を引数として引き回さないために存在します。
    Per-turn state read and written by the phases of execute(). It exists so phases do not have
    to thread a dozen local variables through their signatures.
    """

    request: Request
    session: dict[str, Any]
    auth_limit_service: AuthLimitService | None
    llm_daily_limit_service: LlmDailyLimitService | None
    chat_generation_service: ChatGenerationService | None
    # 日本語: セッションに user_id キーがあるか。ルーム保存先の分岐に使う元の条件をそのまま保つ。
    # English: Whether the session carries a user_id key, preserving the original branch condition.
    authenticated: bool = False
    user_message: str = ""
    chat_room_id: str = ""
    model: str = ""
    attached_files: list[Any] = field(default_factory=list)
    use_personal_knowledge: bool = False
    use_shared_prompts: bool = False
    formatted_user_message: str = ""
    user_id: int | None = None
    sid: str | None = None
    room_mode: str = "temporary"
    prepared_attached_files: list[PreparedAttachedFile] = field(default_factory=list)
    saved_user_message_id: int | None = None
    should_auto_title_room: bool = False
    all_messages: list[dict[str, Any]] = field(default_factory=list)
    normalized_all_messages: list[dict[str, Any]] = field(default_factory=list)
    active_task_request: dict[str, Any] | None = None
    task_prompt: str | None = None
    user_profile_prompt: str | None = None
    user_skills_prompt: str | None = None
    generative_ui_enabled: bool = True
    project_instructions: str | None = None
    room_summary: str = ""
    memory_facts: list[str] = field(default_factory=list)
    conversation_messages: list[dict[str, Any]] = field(default_factory=list)
    # 日本語: 通常ルームでは、発話保存と同じルームツリー読み出しから得た過去ターンの
    #         検索結果。改めて DB を読まないための引き渡し先。
    # English: For DB-backed rooms, the prior-turn search evidence produced by the same
    #          room-tree read that stored the message, so no second query is needed.
    room_web_search_contexts: list[dict[str, Any]] = field(default_factory=list)
    prior_web_search_results: list[WebSearchResult] = field(default_factory=list)
    generation_key: str = ""
    personal_knowledge_search: Callable[[str], dict[str, Any]] | None = None
    shared_prompt_search: Callable[[str], dict[str, Any]] | None = None
    selected_reference_trace: list[SelectedReferenceLookupTrace] = field(default_factory=list)
    ui_mode: GenerativeUiMode | None = None
    bot_reply: str = ""
    message_parts: list[dict[str, Any]] | None = None
    saved_assistant_message_id: int | None = None

    # 添付本文をDBへ渡すかどうかで引数の有無が変わるため、キーワード辞書として組み立てる
    # Built as a keyword dict because the argument is only passed when attachments exist
    def attachment_content_kwargs(self) -> dict[str, Any]:
        if not self.prepared_attached_files:
            return {}
        return {"attached_file_contents": self.prepared_attached_files}

    # 通常ルーム（DB保存対象）かどうか
    # Whether this turn targets a DB-backed normal room
    def targets_normal_room(self) -> bool:
        return self.user_id is not None and self.room_mode == "normal"


# チャット投稿処理（メッセージ保存、RAG/Web検索、LLM呼び出し/ストリーミング、タイトル生成、要約更新）を担うユースケースクラス
# A use case class handling chat posts (saving messages, RAG/Web search, LLM calls/streaming, title generation, and summary updates)
class ChatPostUseCase:
    # ユースケースを依存関係とデフォルトモデル名で初期化する
    # Initialize the use case with dependencies and the default model name
    def __init__(
        self,
        dependencies: ChatPostUseCaseDependencies,
        *,
        default_model: str,
        locale: str = "ja",
    ) -> None:
        self.deps = dependencies
        self.default_model = default_model
        self.locale = locale

    # リクエストを受け取り、メッセージの検証・コンテキスト補強・AI応答生成・DB保存などの一連の流れを実行する
    # Receive a request and execute the entire workflow including validation, context augmentation, AI generation, and database updates
    async def execute(
        self,
        request: Request,
        *,
        auth_limit_service: AuthLimitService | None,
        llm_daily_limit_service: LlmDailyLimitService | None,
        chat_generation_service: ChatGenerationService | None,
    ) -> Response:
        turn = _ChatPostTurn(
            request=request,
            session=request.session,
            auth_limit_service=auth_limit_service,
            llm_daily_limit_service=llm_daily_limit_service,
            chat_generation_service=chat_generation_service,
        )

        for phase in (
            self._parse_request,
            self._consume_guest_daily_limit,
            self._resolve_room_target,
            self._store_user_message,
        ):
            early_response = await phase(turn)
            if early_response is not None:
                return early_response

        await self._build_llm_history(turn)
        await self._load_prompt_context(turn)
        self._build_conversation_messages(turn)
        await self._load_prior_web_search_results(turn)

        for guard in (self._reject_active_generation, self._consume_llm_daily_quota):
            early_response = await guard(turn)
            if early_response is not None:
                return early_response

        await self._augment_with_selected_references(turn)
        await self._decide_generative_ui_mode(turn)

        # ストリーミング対応モデルの場合はバックグラウンドジョブを開始する
        # Start a background generation job if the model supports streaming
        if self.deps.generation.is_streaming_model(turn.model):
            return self._start_streaming_generation(turn)
        return await self._respond_without_streaming(turn)

    # ------------------------------------------------------------------
    # フェーズ1: リクエストの検証 / Phase 1: request validation
    # ------------------------------------------------------------------
    async def _parse_request(self, turn: _ChatPostTurn) -> Response | None:
        """一時チャットを掃除し、リクエストJSONとモデル名を検証します / Clean ephemeral chats, then validate the JSON body and model."""
        deps = self.deps

        # 一時チャットのクリーンアップとリクエストJSONのパース・検証
        # Cleanup ephemeral chats and parse/validate the request JSON payload
        await run_blocking(deps.rooms.cleanup_ephemeral_chats)
        data, error_response = await deps.web.require_json_dict(turn.request)
        if error_response is not None:
            return error_response

        payload, validation_error = deps.web.validate_payload_model(
            data,
            ChatMessageRequest,
            error_message="'message' が必要です。",
        )
        if validation_error is not None:
            return validation_error

        turn.user_message = payload.message
        turn.chat_room_id = payload.chat_room_id
        turn.model = payload.model or self.default_model
        turn.attached_files = payload.attached_files or []
        turn.use_personal_knowledge = bool(payload.use_personal_knowledge)
        turn.use_shared_prompts = bool(payload.use_shared_prompts)

        # モデル名の検証
        # Validate the requested model name
        try:
            deps.limits.validate_model_name(turn.model)
        except LlmInvalidModelError as exc:
            return deps.web.jsonify({"error": str(exc)}, status_code=400)

        turn.authenticated = "user_id" in turn.session
        turn.user_id = turn.session.get("user_id")
        turn.formatted_user_message = html.escape(turn.user_message).replace("\n", "<br>")
        return None

    async def _consume_guest_daily_limit(self, turn: _ChatPostTurn) -> Response | None:
        """ゲスト投稿の日次上限を消費します / Consume the guest daily post limit."""
        deps = self.deps

        # ゲスト制限の消費判定
        # Consume guest limits
        if turn.authenticated:
            return None
        allowed, message = await run_blocking(
            deps.limits.consume_guest_chat_daily_limit,
            turn.request,
            service=turn.auth_limit_service,
        )
        if not allowed:
            return deps.web.jsonify_rate_limited(
                message or "1日10回までです",
                retry_after=deps.limits.get_seconds_until_tomorrow(),
            )
        return None

    # ------------------------------------------------------------------
    # フェーズ2: ルームの解決 / Phase 2: room resolution
    # ------------------------------------------------------------------
    async def _resolve_room_target(self, turn: _ChatPostTurn) -> Response | None:
        """ルーム所有権およびアクセス権のバリデーション / Validate room ownership and access permissions."""
        deps = self.deps

        if turn.authenticated:
            try:
                room_mode, sid, legacy_response = await _maybe_await(
                    deps.rooms.resolve_authenticated_room_target(
                        turn.chat_room_id,
                        turn.user_id,
                        "他ユーザーのチャットルームには投稿できません",
                    )
                )
                if legacy_response is not None:
                    return legacy_response
            except ApiServiceError as exc:
                return deps.web.jsonify_service_error(exc)
            except Exception:
                return deps.web.log_and_internal_server_error(
                    deps.logger,
                    "Failed to validate chat room ownership before posting.",
                )
            turn.room_mode = room_mode
            turn.sid = sid
            return None

        sid, guest_error = await deps.rooms.validate_guest_room_access(turn.session, turn.chat_room_id)
        if guest_error is not None:
            return guest_error
        turn.sid = sid
        return None

    # ------------------------------------------------------------------
    # フェーズ3: ユーザー発話の保存 / Phase 3: persisting the user message
    # ------------------------------------------------------------------
    async def _store_user_message(self, turn: _ChatPostTurn) -> Response | None:
        """添付を検証し、ルーム種別に応じてユーザー発話を保存します / Validate attachments, then store the user message per room type."""
        deps = self.deps

        # 添付ファイルのアップロード準備と検証
        # Prepare and validate uploaded attachment files
        try:
            turn.prepared_attached_files = await run_blocking(prepare_attached_files, turn.attached_files)
        except AttachedFileValidationError as exc:
            return deps.web.jsonify({"error": str(exc)}, status_code=400)

        # 一時ルームと通常ルームで分岐し、ユーザー発話メッセージを保存する
        # Save the user message depending on temporary vs. normal room mode
        if turn.authenticated:
            if turn.room_mode == "temporary":
                await self._store_user_message_in_temporary_room(turn)
            else:
                await self._store_user_message_in_normal_room(turn)
        else:
            await self._store_guest_user_message(turn)
        return None

    async def _store_user_message_in_temporary_room(self, turn: _ChatPostTurn) -> None:
        """ログイン中の一時ルームへ発話を保存します / Store the message in a signed-in user's temporary room."""
        deps = self.deps

        # ログイン中でも temporary room は DB に保存せず、ユーザー単位の一時ストアに閉じ込める。
        # sid ではなく user_id 由来のキーを使うため、同じユーザーの再読み込みにも耐える。
        turn.sid = deps.rooms.get_temporary_user_store_key(turn.user_id)
        await run_blocking(deps.rooms.ensure_ephemeral_room, turn.sid, turn.chat_room_id)
        await run_blocking(
            deps.rooms.ephemeral_store.append_message,
            turn.sid,
            turn.chat_room_id,
            "user",
            turn.formatted_user_message,
            **turn.attachment_content_kwargs(),
        )
        turn.all_messages = await run_blocking(
            deps.rooms.ephemeral_store.get_messages,
            turn.sid,
            turn.chat_room_id,
        )

    async def _store_user_message_in_normal_room(self, turn: _ChatPostTurn) -> None:
        """DB保存ルームへ発話を保存し、初回ターンかどうかを判定します / Store the message in a DB-backed room and detect a first turn."""
        deps = self.deps

        attached_file_name_list = (
            [f.name for f in turn.prepared_attached_files] if turn.prepared_attached_files else None
        )
        # 保存と文脈読み出しを1トランザクションへまとめる。新しい発話は能動枝の末尾へ繋がるため、
        # 親の決定・LLM履歴・過去ターンの検索結果はすべて同じ1回のツリー読み出しから導ける。
        # Persisting and loading share one transaction. A new turn extends the active branch, so the
        # parent, the LLM history and the prior search evidence all come from the same tree read.
        context = await _maybe_await(
            deps.persistence.store_user_message_and_load_turn_context(
                turn.chat_room_id,
                turn.formatted_user_message,
                "user",
                attached_file_name_list,
                None,
                turn.prepared_attached_files or None,
            )
        )
        turn.saved_user_message_id = context.get("message_id")
        # 初回発話では assistant 応答がまだない。このフラグは初回タイトル自動生成にも使う。
        # A first turn has no assistant reply yet; the flag also drives the initial auto-title.
        turn.should_auto_title_room = bool(context.get("is_first_turn"))
        turn.all_messages = list(context.get("messages") or [])
        turn.room_web_search_contexts = list(context.get("web_search_contexts") or [])

    async def _store_guest_user_message(self, turn: _ChatPostTurn) -> None:
        """未ログインの一時ルームへ発話を保存します / Store the message in a guest's temporary room."""
        deps = self.deps

        await run_blocking(
            deps.rooms.ephemeral_store.append_message,
            turn.sid,
            turn.chat_room_id,
            "user",
            turn.formatted_user_message,
            **turn.attachment_content_kwargs(),
        )
        turn.all_messages = await run_blocking(
            deps.rooms.ephemeral_store.get_messages,
            turn.sid,
            turn.chat_room_id,
        )

    # ------------------------------------------------------------------
    # フェーズ4: LLM向け履歴の組み立て / Phase 4: building the LLM history
    # ------------------------------------------------------------------
    async def _build_llm_history(self, turn: _ChatPostTurn) -> None:
        """
        履歴を正規化し、添付とURL本文を参照資料として差し込みます
        Normalize history and inject attachments and URL bodies as reference material.
        """
        # メッセージ履歴を LLM 向けに正規化
        # Normalize message history for LLM compatibility
        turn.normalized_all_messages = self.deps.prompts.normalize_messages_for_llm(turn.all_messages)
        self._reattach_prior_uploads(turn)
        await self._prepend_reference_blocks(turn)

    def _reattach_prior_uploads(self, turn: _ChatPostTurn) -> None:
        """過去ターンの添付を、その発話に紐づく参照資料として戻します / Re-attach earlier uploads to the message they belong to."""
        # 過去ターンの添付も、そのメッセージに紐づく参照資料として再投入する。
        # 最新ターンの添付は下の prefix_blocks で追加するため、ここでは重複を避ける。
        # Reintroduce earlier uploads with the turn they belong to. The newest
        # upload is added below through prefix_blocks, so it is not duplicated.
        normalized_all_messages = turn.normalized_all_messages
        latest_user_index = next(
            (
                index
                for index in range(len(normalized_all_messages) - 1, -1, -1)
                if normalized_all_messages[index].get("role") == "user"
            ),
            None,
        )
        if latest_user_index is None:
            return

        updated_messages = list(normalized_all_messages)
        for index, message in enumerate(normalized_all_messages):
            if index == latest_user_index or message.get("role") != "user":
                continue
            prior_attached_files = decode_attached_files_from_storage(
                message.get("attached_file_contents")
            )
            if not prior_attached_files:
                continue
            updated_messages[index] = {
                **message,
                "content": (
                    f"{format_attached_files_for_prompt(prior_attached_files)}\n\n"
                    f"{message.get('content', '')}"
                ),
            }
        turn.normalized_all_messages = updated_messages

    async def _prepend_reference_blocks(self, turn: _ChatPostTurn) -> None:
        """
        取得したURL本文と今回の添付を最新発話へ前置します
        Prepend fetched URL bodies and this turn's attachments to the latest message.
        """
        # Build context blocks to prepend to the last user message.
        # Order: fetched URL content → attached file content → user message text.
        prefix_blocks: list[str] = []

        # メッセージからのURL抽出およびコンテンツ取得
        # Extract URLs from the user message and fetch their web contents
        urls_in_message = extract_urls_from_text(turn.user_message)
        if urls_in_message:
            # URL 本文は「ユーザーが渡した参照資料」として直近 user message にだけ付与する。
            # system message に混ぜると、外部ページ本文が指示階層を持っているように見えやすい。
            fetched_urls = await run_blocking(fetch_urls_content, urls_in_message)
            if fetched_urls:
                url_xml = "\n".join(
                    f'<url href="{url}">\n{content}\n</url>'
                    for url, content in fetched_urls.items()
                )
                prefix_blocks.append(f"<fetched_urls>\n{url_xml}\n</fetched_urls>")
            else:
                prefix_blocks.append(
                    "<fetched_urls_status>\n"
                    "The linked page content could not be retrieved. Do not summarize or infer details "
                    "from the URL alone; ask the user for the page text or another accessible source if "
                    "the request depends on it.\n"
                    "</fetched_urls_status>"
                )

        if turn.prepared_attached_files:
            prefix_blocks.append(format_attached_files_for_prompt(turn.prepared_attached_files))

        normalized_all_messages = turn.normalized_all_messages
        if prefix_blocks and normalized_all_messages and normalized_all_messages[-1].get("role") == "user":
            prefix = "\n\n".join(prefix_blocks)
            last_msg = normalized_all_messages[-1]
            turn.normalized_all_messages = [
                *normalized_all_messages[:-1],
                {**last_msg, "content": f"{prefix}\n\n{last_msg.get('content', '')}"},
            ]

    # ------------------------------------------------------------------
    # フェーズ5: プロンプト文脈の読み込み / Phase 5: loading prompt context
    # ------------------------------------------------------------------
    async def _load_prompt_context(self, turn: _ChatPostTurn) -> None:
        """タスク定義・スキル・プロジェクト・記憶をまとめて読み込みます / Load task definitions, skills, project context and memory."""
        await self._load_task_prompt(turn)
        await self._load_user_skills_and_profile(turn)
        await self._load_project_instructions(turn)
        await self._load_room_memory(turn)

    async def _load_task_prompt(self, turn: _ChatPostTurn) -> None:
        """最新のタスク起動リクエストと定義プロンプトの読み込み / Load the latest task launch request and corresponding task definitions."""
        deps = self.deps

        turn.active_task_request = deps.prompts.find_latest_task_launch_request(turn.normalized_all_messages)
        prompt_data = None
        if turn.active_task_request is not None:
            task_id = turn.active_task_request.get("task_id")
            if task_id is None:
                prompt_data = await deps.prompts.load_task_prompt_data(
                    turn.active_task_request["task"], turn.user_id
                )
            else:
                prompt_data = await deps.prompts.load_task_prompt_data(
                    turn.active_task_request["task"], turn.user_id, task_id
                )

        turn.task_prompt = deps.prompts.build_task_prompt(prompt_data) if prompt_data else None

    async def _load_user_skills_and_profile(self, turn: _ChatPostTurn) -> None:
        """ユーザープロフィールプロンプトと有効なスキル文脈の構築 / Build the user profile prompt and enabled-skill context."""
        deps = self.deps

        enabled_user_skills: list[dict[str, Any]] = []
        user = None
        if turn.user_id is not None:
            try:
                if deps.prompts.load_enabled_user_skills is not None:
                    enabled_user_skills = list(
                        await _maybe_await(deps.prompts.load_enabled_user_skills(turn.user_id)) or []
                    )
            except Exception:
                deps.logger.warning("Failed to load enabled user skills; proceeding without them.")
            try:
                user = await _maybe_await(deps.prompts.get_user_by_id(turn.user_id))
                turn.user_profile_prompt = deps.prompts.build_user_profile_prompt(user)
            except Exception:
                deps.logger.warning("Failed to load user profile context; proceeding without it.")

        turn.user_skills_prompt, turn.generative_ui_enabled = build_chat_skills_context(
            enabled_user_skills,
            user,
            locale=self.locale,
            prompt_builder=deps.prompts.build_user_skills_prompt,
        )

    async def _load_project_instructions(self, turn: _ChatPostTurn) -> None:
        """
        通常のユーザーセッションの場合、所属プロジェクトの指示を読み込む
        For normal user sessions, load the owning project's instructions.
        """
        deps = self.deps

        if not turn.targets_normal_room():
            return
        try:
            project_context = await _maybe_await(deps.persistence.load_project_context(turn.chat_room_id))
            if project_context:
                turn.project_instructions = str(project_context.get("instructions") or "") or None
        except Exception:
            deps.logger.warning("Failed to load project context; proceeding without it.")

    async def _load_room_memory(self, turn: _ChatPostTurn) -> None:
        """
        通常のユーザーセッションの場合、要約とパーソナル記憶情報の読み込みと抽出
        For normal user sessions, load summaries and extract/load personal memory facts.
        """
        deps = self.deps

        if not turn.targets_normal_room():
            return
        if not turn.should_auto_title_room:
            try:
                summary_payload = await _maybe_await(deps.persistence.get_room_summary(turn.chat_room_id))
                turn.room_summary = str((summary_payload or {}).get("summary") or "")
            except Exception:
                deps.logger.warning("Failed to load room summary; proceeding without it.")
            try:
                turn.memory_facts = await _maybe_await(
                    deps.persistence.list_room_memory_facts(turn.chat_room_id)
                )
            except Exception:
                deps.logger.warning("Failed to load memory facts; proceeding without them.")
        if turn.saved_user_message_id is not None:
            self._defer_memory_fact_update(turn)

    def _defer_memory_fact_update(self, turn: _ChatPostTurn) -> None:
        """記憶抽出を応答経路の外へ回します / Move memory extraction off the response path."""
        deps = self.deps
        chat_room_id = turn.chat_room_id
        user_id = turn.user_id
        user_message = turn.user_message
        saved_user_message_id = turn.saved_user_message_id

        # 記憶抽出は元メッセージIDと結びつけて保存する。抽出自体がLLM呼び出しに
        # なったため応答経路から外す。今ターンの発話は履歴としてそのまま文脈に
        # 入っているので、抽出結果が要るのは次ターン以降であり遅延は問題ない。
        # Memory extraction is tied to the source message id. It now costs an
        # LLM call, so it runs off the response path: this turn already carries
        # the user's message verbatim, and the extracted facts are only needed
        # from the next turn onward.
        try:
            deps.background.submit_background_task(
                _run_async_callback,
                lambda: deps.persistence.remember_facts_from_message(
                    chat_room_id,
                    user_id,
                    user_message,
                    source_message_id=saved_user_message_id,
                ),
            )
        except Exception:
            deps.logger.warning(
                "Failed to schedule memory fact update for chat room %s.",
                chat_room_id,
            )

    # ------------------------------------------------------------------
    # フェーズ6: 会話メッセージの構築 / Phase 6: assembling conversation messages
    # ------------------------------------------------------------------
    def _build_conversation_messages(self, turn: _ChatPostTurn) -> None:
        """システムプロンプトおよびコンテキストメッセージの構築 / Assemble context messages including base system prompts."""
        deps = self.deps

        turn.conversation_messages = deps.prompts.build_context_messages(
            base_system_prompt=deps.prompts.build_base_system_prompt(),
            user_profile_prompt=turn.user_profile_prompt,
            task_prompt=turn.task_prompt,
            room_summary=turn.room_summary,
            memory_facts=turn.memory_facts,
            recent_messages=turn.normalized_all_messages,
            project_instructions=turn.project_instructions,
            user_skills_prompt=turn.user_skills_prompt,
            generative_ui_enabled=turn.generative_ui_enabled,
        )

    async def _load_prior_web_search_results(self, turn: _ChatPostTurn) -> None:
        """
        過去ターンで取得した検索結果を読み込み、後続の生成で参照用文脈として再注入する
        Load prior-turn search results to re-inject as reference context during generation.
        """
        if turn.targets_normal_room():
            # 発話保存と同じツリー読み出しで得た結果を使う。初回ターンでは空のまま。
            # Reuse the evidence from the tree read that stored the message; empty on a first turn.
            turn.prior_web_search_results = deserialize_web_search_results(turn.room_web_search_contexts)
        else:
            turn.prior_web_search_results = extract_prior_web_search_results(turn.all_messages)

    # ------------------------------------------------------------------
    # フェーズ7: 生成前のガード / Phase 7: pre-generation guards
    # ------------------------------------------------------------------
    async def _reject_active_generation(self, turn: _ChatPostTurn) -> Response | None:
        """生成キーの構築と二重送信防止ロック / Build the generation key and check for active running jobs."""
        deps = self.deps

        turn.generation_key = deps.generation.build_generation_key(
            chat_room_id=turn.chat_room_id,
            user_id=turn.user_id,
            sid=turn.sid,
        )
        if deps.generation.has_active_generation(turn.generation_key, service=turn.chat_generation_service):
            return deps.web.jsonify(
                {"error": _GENERATION_ALREADY_RUNNING_MESSAGE},
                status_code=409,
            )
        return None

    async def _consume_llm_daily_quota(self, turn: _ChatPostTurn) -> Response | None:
        """LLM利用クォータ制限のチェック / Check daily LLM usage quotas."""
        deps = self.deps

        quota_user_key: str | None
        if turn.user_id is not None:
            quota_user_key = f"user:{turn.user_id}"
        elif turn.sid:
            quota_user_key = f"sid:{turn.sid}"
        else:
            quota_user_key = None
        can_access_llm, _, daily_limit = await run_blocking(
            deps.limits.consume_llm_daily_quota,
            service=turn.llm_daily_limit_service,
            user_key=quota_user_key,
        )
        if can_access_llm:
            return None

        # quota 失敗時にユーザー発話だけを残すと、次回の文脈が「未回答の発話」から始まる。
        # そのため通常ルーム/一時ルームの差を吸収して、assistant 応答なしの投稿を掃除する。
        await self._discard_unanswered_user_message(turn)
        return deps.web.jsonify_rate_limited(
            (
                f"本日のLLM API利用上限（1ユーザーあたり {daily_limit} 回）に達しました。"
                "日付が変わってから再度お試しください。"
            ),
            retry_after=deps.limits.get_seconds_until_daily_reset(),
        )

    # ------------------------------------------------------------------
    # フェーズ8: 参照元の事前検索とUIモード判定 / Phase 8: reference prefetch and UI mode
    # ------------------------------------------------------------------
    async def _augment_with_selected_references(self, turn: _ChatPostTurn) -> None:
        """
        選択された参照元を生成前に検索し、参照文脈へ入れます
        Prefetch the selected reference sources into the context before generation.
        """
        deps = self.deps

        # 選択されたメモ／共有プロンプトは、モデルがツールを呼ぶかどうかに任せず、
        # 生成開始前に必ず検索して参照文脈へ入れる。ツール自体も追加検索用に残す。
        # Always load user-selected memo/shared-prompt sources before generation instead
        # of relying on the model to decide whether to call their tools. Keep the tools
        # available as well so the model can retry with narrower keywords when needed.
        selected_references = build_selected_reference_searchers(
            user_id=turn.user_id,
            use_personal_knowledge=turn.use_personal_knowledge,
            use_shared_prompts=turn.use_shared_prompts,
            search_personal_knowledge=deps.generation.search_personal_knowledge,
            search_shared_prompts=deps.generation.search_shared_prompts,
        )
        turn.personal_knowledge_search = selected_references.personal_knowledge
        turn.shared_prompt_search = selected_references.shared_prompt
        turn.selected_reference_trace = []
        turn.conversation_messages = await augment_messages_with_selected_references_async(
            turn.conversation_messages,
            query=turn.user_message,
            personal_knowledge_search=turn.personal_knowledge_search,
            shared_prompt_search=turn.shared_prompt_search,
            personal_overview=selected_references.personal_overview,
            unavailable_sources=selected_references.unavailable_sources,
            trace_results=turn.selected_reference_trace,
        )

    async def _decide_generative_ui_mode(self, turn: _ChatPostTurn) -> None:
        """生成UIのモードをモデルへ問い合わせます / Ask the model for the generative UI mode."""
        deps = self.deps

        # UI_MODE is a structured semantic decision made by the selected
        # conversation model. Do not infer it from the user's text here.
        if turn.generative_ui_enabled:
            try:
                turn.ui_mode = await run_blocking(
                    deps.generation.decide_generative_ui_mode,
                    turn.conversation_messages,
                    turn.model,
                )
            except Exception:
                deps.logger.warning(
                    "Failed to decide generative UI mode; continuing without intent recovery.",
                    exc_info=True,
                )
                turn.ui_mode = None
        else:
            turn.ui_mode = "NONE"

    # ------------------------------------------------------------------
    # フェーズ9a: ストリーミング生成 / Phase 9a: streaming generation
    # ------------------------------------------------------------------
    def _start_streaming_generation(self, turn: _ChatPostTurn) -> Response:
        """バックグラウンド生成ジョブを開始し、SSEレスポンスを返します / Start the background generation job and return the SSE response."""
        deps = self.deps

        on_finished: Callable[[], None] | None = None
        persist_response: Callable[..., dict[str, Any] | None]
        if turn.targets_normal_room():
            persist_response, on_finished = self._build_normal_room_stream_callbacks(turn)
        else:
            persist_response = partial(
                deps.rooms.ephemeral_store.append_message,
                turn.sid,
                turn.chat_room_id,
                "assistant",
            )

        try:
            job = deps.generation.start_generation_job(
                turn.generation_key,
                conversation_messages=turn.conversation_messages,
                model=turn.model,
                persist_response=persist_response,
                on_finished=on_finished,
                on_error=partial(
                    _run_async_callback,
                    lambda: _maybe_await(
                        deps.persistence.cleanup_unanswered_user_messages(
                            turn.chat_room_id,
                            user_id=turn.user_id,
                            sid=turn.sid,
                        )
                    ),
                ),
                service=turn.chat_generation_service,
                prior_web_search_results=turn.prior_web_search_results,
                personal_knowledge_search=turn.personal_knowledge_search,
                shared_prompt_search=turn.shared_prompt_search,
                selected_reference_trace=turn.selected_reference_trace,
                ui_mode=turn.ui_mode,
            )
        except ChatGenerationAlreadyRunningError:
            return deps.web.jsonify(
                {"error": _GENERATION_ALREADY_RUNNING_MESSAGE},
                status_code=409,
            )

        return deps.web.build_llm_stream_response(deps.web.iter_llm_stream_events(job))

    def _build_normal_room_stream_callbacks(
        self,
        turn: _ChatPostTurn,
    ) -> tuple[Callable[..., dict[str, Any] | None], Callable[[], None]]:
        """DB保存ルーム向けの保存・完了コールバックを組み立てます / Build the persist and completion callbacks for a DB-backed room."""
        deps = self.deps
        chat_room_id = turn.chat_room_id
        model = turn.model
        user_id = turn.user_id
        room_mode = turn.room_mode
        user_message = turn.user_message
        saved_user_message_id = turn.saved_user_message_id
        should_auto_title_room = turn.should_auto_title_room
        # 要約入力はこのターンの履歴＋保存できた応答で決まる。DBを読み直さない。
        # The summary input is this turn's history plus the reply that was persisted; no re-read.
        history_before_reply = list(turn.all_messages)
        persisted_reply: list[str] = []

        title_candidates = build_initial_title_candidates(
            user_message,
            task_launch_request=turn.active_task_request,
        )

        def persist_response(
            response: str,
            *,
            message_parts: list[dict[str, Any]] | None = None,
            web_search_context: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any] | None:
            assistant_message_id = _run_async_callback(
                lambda: _maybe_await(
                    deps.persistence.save_message_to_db(
                        chat_room_id,
                        response,
                        "assistant",
                        None,
                        saved_user_message_id,
                        message_parts,
                        None,
                        web_search_context,
                    )
                )
            )
            if assistant_message_id is None:
                # A missing id means the persistence boundary did not commit the reply. Do not
                # let on_finished summarize a turn that is absent from the room history.
                return None
            persisted_reply.append(response)
            self._defer_context_extraction(
                user_id=user_id,
                room_mode=room_mode,
                chat_room_id=chat_room_id,
                assistant_message_id=assistant_message_id,
                user_message=user_message,
                assistant_response=response,
            )
            # 初回応答を保存できた後にだけタイトルを自動生成する。
            # ユーザーが先に改名していた場合は conditional rename が更新を拒否する。
            if not should_auto_title_room:
                return None
            generated_title = _run_async_callback(
                lambda: self._generate_and_rename_room(
                    chat_room_id=chat_room_id,
                    user_message=user_message,
                    assistant_response=response,
                    allowed_current_titles=title_candidates,
                )
            )
            if generated_title:
                return {"room_title": generated_title}
            return None

        def on_finished() -> None:
            # 応答を保存できなかったターンは履歴が変わっていないため、要約も作り直さない。
            # A turn whose reply was never persisted left the history unchanged, so skip the rebuild.
            if not persisted_reply:
                return
            try:
                updated_messages = _messages_including_reply(history_before_reply, persisted_reply[-1])
                # 要約はストリーミング完了後に一度だけ更新する。
                # chunk 単位で更新すると未完成の応答が要約へ混ざり、DB 書き込みも増える。
                _run_async_callback(
                    lambda: _maybe_await(
                        deps.persistence.rebuild_room_summary(
                            chat_room_id,
                            updated_messages,
                            model=model,
                        )
                    )
                )
            except Exception:
                deps.logger.warning(
                    "Failed to rebuild room summary after streaming response for %s.",
                    chat_room_id,
                )

        return persist_response, on_finished

    # ------------------------------------------------------------------
    # フェーズ9b: 非ストリーミング生成 / Phase 9b: non-streaming generation
    # ------------------------------------------------------------------
    async def _respond_without_streaming(self, turn: _ChatPostTurn) -> Response:
        """
        互換用の同期経路で応答を生成し、保存してから返します
        Generate, persist and return the reply on the synchronous compatibility path.
        """
        deps = self.deps

        # 対応モデルは通常ストリーミング経路へ入る。互換用の同期経路では事前検索Plannerを
        # 起動せず、取得済みの参照だけでモデル自身に回答させる。
        # Supported models normally use the streaming agent loop. This compatibility fallback
        # never runs a separate search planner; it answers from already available references.
        turn.conversation_messages = inject_prior_web_search_context(
            turn.conversation_messages, turn.prior_web_search_results
        )

        error_response = await self._request_llm_reply(turn)
        if error_response is not None:
            return error_response

        await self._finalize_reply(turn)
        empty_reply_response = await self._reject_empty_reply(turn)
        if empty_reply_response is not None:
            return empty_reply_response

        generated_room_title = await self._persist_assistant_reply(turn)
        await self._rebuild_room_summary_after_reply(turn)

        response_payload: dict[str, Any] = {"response": turn.bot_reply}
        if turn.message_parts:
            response_payload["parts"] = turn.message_parts
        if generated_room_title:
            response_payload["room_title"] = generated_room_title
        return deps.web.jsonify(response_payload)

    async def _request_llm_reply(self, turn: _ChatPostTurn) -> Response | None:
        """LLMを呼び出し、失敗はユーザー向けレスポンスへ変換します / Call the LLM and turn failures into user-facing responses."""
        deps = self.deps

        try:
            bot_reply = await run_blocking(
                deps.generation.get_llm_response, turn.conversation_messages, turn.model
            )
        except LlmInvalidModelError as exc:
            await self._discard_unanswered_user_message(turn)
            return deps.web.jsonify({"error": str(exc)}, status_code=400)
        except LlmRateLimitError as exc:
            await self._discard_unanswered_user_message(turn)
            return deps.web.jsonify_rate_limited(
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
            await self._discard_unanswered_user_message(turn)
            return deps.web.jsonify(
                {"error": "AI設定エラーが発生しました。管理者に連絡してください。"},
                status_code=502,
            )
        except LlmServiceError as exc:
            retryable = deps.generation.is_retryable_llm_error(exc)
            deps.logger.exception(
                "Failed to get LLM response (retryable=%s).",
                retryable,
            )
            await self._discard_unanswered_user_message(turn)
            return deps.web.jsonify(
                {
                    "error": "AI応答の生成に失敗しました。時間をおいて再試行してください。",
                    "retryable": retryable,
                },
                status_code=502,
            )

        turn.bot_reply = bot_reply
        return None

    async def _finalize_reply(self, turn: _ChatPostTurn) -> None:
        """トレース前置・UIパーツ正規化・出典解決を保存前に確定します / Settle trace, UI parts and citations before persisting."""
        self._prepend_selected_reference_trace(turn)
        await self._normalize_generated_reply(turn)
        self._resolve_reply_citations(turn)

        # 保存直前にトレース分割と本文内の画像位置を確定する。
        # Finalize trace splitting and inline image placement before persisting.
        if turn.message_parts:
            turn.message_parts = normalize_message_parts_for_display(turn.message_parts) or None

    def _prepend_selected_reference_trace(self, turn: _ChatPostTurn) -> None:
        """参照検索のステップを本文の先頭へ付けます / Prepend the reference-lookup steps to the reply body."""
        web_search_trace_steps: list[TraceStep] = selected_reference_steps(
            turn.selected_reference_trace
        )
        if web_search_trace_steps:
            web_search_trace_steps.append(answer_step([]))
        trace_block = build_web_search_trace_markdown(
            None,
            steps=web_search_trace_steps,
        )
        # 本文の無いターンにトレースだけを前置すると空判定をすり抜け、「回答までの
        # ステップ」だけの応答が保存される。本文があるときだけ前置する。
        # Prepending the trace to an empty body would slip past the empty-answer guard and
        # persist a steps-only reply, so only a non-empty body receives the trace.
        if trace_block and turn.bot_reply.strip():
            turn.bot_reply = f"{trace_block}\n\n{turn.bot_reply}"

    async def _normalize_generated_reply(self, turn: _ChatPostTurn) -> None:
        """
        生成UIアーティファクトを検証し、本文とパーツへ分解します
        Validate generated UI artifacts and split the reply into text and parts.
        """
        deps = self.deps

        normalized_response = await run_blocking(
            partial(
                normalize_response_with_artifact_retry,
                conversation_messages=turn.conversation_messages,
                model=turn.model,
                generate_response=deps.generation.get_llm_response,
                user_request=turn.user_message,
                ui_mode=turn.ui_mode,
            ),
            turn.bot_reply,
        )
        if normalized_response.validation_errors:
            deps.logger.warning(
                "One or more generated UI artifacts failed validation and were omitted.",
                extra={"validation_errors": normalized_response.validation_errors},
            )
        turn.bot_reply = normalized_response.text
        turn.message_parts = normalized_response.parts

    def _resolve_reply_citations(self, turn: _ChatPostTurn) -> None:
        """出典marker を検証済みの検索結果へ解決します / Resolve citation markers against the validated search evidence."""
        deps = self.deps

        # モデルが真似て書いた出典チップHTMLを、引用marker解決の前に取り除く。
        # Remove chip markup echoed by the model before resolving citation markers.
        turn.bot_reply = strip_web_search_citation_html(turn.bot_reply)
        citation_evidence = combine_web_search_results(
            turn.prior_web_search_results
        )
        if citation_evidence is None:
            return

        citation_resolution = resolve_web_search_citations(
            turn.bot_reply,
            citation_evidence,
        )
        if citation_resolution.invalid_markers:
            deps.logger.warning(
                "Removed invalid web search citation markers from generated response.",
                extra={
                    "invalid_marker_count": len(citation_resolution.invalid_markers)
                },
            )
        turn.bot_reply = citation_resolution.text
        if turn.message_parts:
            turn.message_parts = [
                (
                    {**part, "text": turn.bot_reply}
                    if part.get("type") == "text"
                    else part
                )
                for part in turn.message_parts
            ]

    async def _reject_empty_reply(self, turn: _ChatPostTurn) -> Response | None:
        """空の応答を保存せずエラーとして返します / Reject an empty reply instead of persisting it."""
        deps = self.deps

        # 本文もUIパーツも空なら回答が無いのと同じ。空の応答を保存すると空の吹き出しが
        # 残り、次のターン以降もユーザー発話だけが積み上がってしまう。
        # An empty body with no UI parts is the same as no answer at all. Persisting
        # it would leave a blank bubble and let unanswered user messages pile up.
        if turn.bot_reply.strip() or turn.message_parts:
            return None

        deps.logger.warning(
            "Chat generation produced an empty response.",
            extra={"chat_room_id": turn.chat_room_id, "model": turn.model},
        )
        await self._discard_unanswered_user_message(turn)
        return deps.web.jsonify(
            {"error": ERROR_CHAT_EMPTY_RESPONSE, "retryable": True},
            status_code=502,
        )

    async def _persist_assistant_reply(self, turn: _ChatPostTurn) -> str | None:
        """応答を保存し、初回ターンなら生成したタイトルを返します / Persist the reply and return the generated title on a first turn."""
        deps = self.deps

        # この互換経路は検索を行わないため、このターンの検索結果は保存しない。
        # This compatibility path never searches, so it stores no results for later turns.
        this_turn_web_search = None

        if not turn.targets_normal_room():
            turn.sid = turn.sid or deps.rooms.get_session_id(turn.session)
            await run_blocking(
                deps.rooms.ephemeral_store.append_message,
                turn.sid,
                turn.chat_room_id,
                "assistant",
                turn.bot_reply,
                turn.message_parts or None,
                None,
                this_turn_web_search,
            )
            return None

        turn.saved_assistant_message_id = await _maybe_await(
            deps.persistence.save_message_to_db(
                turn.chat_room_id,
                turn.bot_reply,
                "assistant",
                None,
                turn.saved_user_message_id,
                turn.message_parts or None,
                None,
                this_turn_web_search,
            )
        )
        self._defer_context_extraction(
            user_id=turn.user_id,
            room_mode=turn.room_mode,
            chat_room_id=turn.chat_room_id,
            assistant_message_id=turn.saved_assistant_message_id,
            user_message=turn.user_message,
            assistant_response=turn.bot_reply,
        )
        if not turn.should_auto_title_room:
            return None
        title_candidates = build_initial_title_candidates(
            turn.user_message,
            task_launch_request=turn.active_task_request,
        )
        return await self._generate_and_rename_room(
            chat_room_id=turn.chat_room_id,
            user_message=turn.user_message,
            assistant_response=turn.bot_reply,
            allowed_current_titles=title_candidates,
        )

    async def _rebuild_room_summary_after_reply(self, turn: _ChatPostTurn) -> None:
        """保存済みの応答を含めてルーム要約を作り直します / Rebuild the room summary including the persisted reply."""
        deps = self.deps

        if not (turn.targets_normal_room() and turn.saved_assistant_message_id is not None):
            return
        try:
            # 保存済みの応答はこのターンの履歴の末尾に足したものと一致する。
            # The persisted reply is exactly this turn's history with the reply appended.
            all_messages = _messages_including_reply(turn.all_messages, turn.bot_reply)
            await _maybe_await(
                deps.persistence.rebuild_room_summary(
                    turn.chat_room_id,
                    all_messages,
                    model=turn.model,
                )
            )
        except Exception:
            deps.logger.warning(
                "Failed to rebuild room summary for chat room %s.",
                turn.chat_room_id,
            )

    # ------------------------------------------------------------------
    # 共通ヘルパー / Shared helpers
    # ------------------------------------------------------------------
    async def _discard_unanswered_user_message(self, turn: _ChatPostTurn) -> None:
        """回答が付かなかったこのターンのユーザー発話を掃除します / Clean up this turn's unanswered user message."""
        await _maybe_await(
            self.deps.persistence.cleanup_unanswered_user_messages(
                turn.chat_room_id,
                user_id=turn.user_id,
                sid=turn.sid,
            )
        )

    async def _generate_and_rename_room(
        self,
        *,
        chat_room_id: str,
        user_message: str,
        assistant_response: str,
        allowed_current_titles: list[str],
    ) -> str | None:
        """Generate a title off-loop, then conditionally persist it through AsyncSession."""
        title = await asyncio.to_thread(
            generate_chat_room_title,
            user_message,
            assistant_response,
            locale=self.locale,
        )
        if not title or title in allowed_current_titles:
            return None
        try:
            updated = await _maybe_await(
                self.deps.persistence.rename_chat_room_if_current_title_in(
                    chat_room_id,
                    title,
                    allowed_current_titles,
                )
            )
        except Exception:
            self.deps.logger.exception("Failed to update generated chat room title.")
            return None
        return title if updated else None

    async def _maybe_schedule_context_extraction(
        self,
        *,
        user_id: int | None,
        room_mode: str,
        chat_room_id: str,
        assistant_message_id: int | None,
        user_message: str,
        assistant_response: str,
    ) -> None:
        """Schedule candidate extraction only for eligible, persisted normal-room turns."""
        if user_id is None or room_mode != "normal" or assistant_message_id is None:
            return
        try:
            if not await _maybe_await(self.deps.background.should_extract_context(user_id)):
                return
            self.deps.background.schedule_context_extraction(
                user_id,
                room_id=chat_room_id,
                assistant_message_id=assistant_message_id,
                user_message=user_message,
                assistant_response=assistant_response,
                locale=self.locale,
            )
        except Exception:
            self.deps.logger.warning(
                "Failed to schedule context extraction for chat room %s.",
                chat_room_id,
                exc_info=True,
            )

    def _defer_context_extraction(
        self,
        *,
        user_id: int | None,
        room_mode: str,
        chat_room_id: str,
        assistant_message_id: int | None,
        user_message: str,
        assistant_response: str,
    ) -> None:
        """Run eligibility checking off the response path, then schedule extraction."""
        if user_id is None or room_mode != "normal" or assistant_message_id is None:
            return
        try:
            self.deps.background.submit_background_task(
                _run_async_callback,
                lambda: self._maybe_schedule_context_extraction(
                    user_id=user_id,
                    room_mode=room_mode,
                    chat_room_id=chat_room_id,
                    assistant_message_id=assistant_message_id,
                    user_message=user_message,
                    assistant_response=assistant_response,
                ),
            )
        except Exception:
            self.deps.logger.warning(
                "Failed to defer context extraction for chat room %s.",
                chat_room_id,
                exc_info=True,
            )
