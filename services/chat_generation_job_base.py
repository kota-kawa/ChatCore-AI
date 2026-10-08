"""生成ジョブ1件の状態と、イベント配信・保存・停止を持つ基底クラス。

The base class holding one generation job's state plus event delivery, persistence and stopping.

`ChatGenerationJob` の可変状態はすべてここの `__init__` が作る。生成ループの各フェーズ
（LLM ストリーム、回答の配信、ツール実行、判断ループ、仕上げ）は別モジュールの Mixin が
担い、この基底クラスを継承して同じ状態を読み書きする。
Every piece of mutable state of `ChatGenerationJob` is created by `__init__` here. The phases of
the generation loop (LLM stream, answer delivery, tool execution, decision loop, finalization) are
mixins in their own modules; each inherits this base class and reads and writes the same state.
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, TimeoutError
from typing import Any

from services.generative_ui import (
    GenerativeUiMode,
    normalize_response_with_artifacts,
)
from services.i18n import normalize_locale, translate_text
from services.interactive_buttons import INTERACTIVE_BUTTONS_PART_TYPE
from services.message_parts_display import normalize_message_parts_for_display
from services.tool_approval_parts import tool_approval_part

from .chat_answer_continuation import (
    looks_like_restarted_answer,
    splice_restarted_answer,
    strip_continuation_overlap,
)
from .chat_generation_coordinator import (
    REMOTE_CANCEL_CHECK_INTERVAL_SECONDS,
    ChatGenerationEvent,
)
from .chat_generation_executor import submit_generation_task
from .chat_generation_telemetry import ChatGenerationTelemetry
from .chat_turn_state import (
    parse_bare_turn_state_update,
    parse_turn_state_update,
    strip_turn_state_update,
)
from .chat_url_context import PastedUrlPage
from .chat_workspace_tools.registry import ChatWorkspaceToolbox
from .chat_workspace_tools.runner import WorkspaceToolRunner
from .chat_write_claim_guard import _unconfirmed_write_claim_fallback
from .generative_ui_images import attach_web_search_images_to_artifacts
from .selected_reference_context import SelectedReferenceLookupTrace
from .web_search import WebSearchResult
from .web_search_images import append_web_search_image_parts

logger = logging.getLogger(__name__)


# 本文イベントが無い間に SSE へ keepalive を送る間隔の既定値。
# Default interval for SSE keepalives while no body event is flowing.
DEFAULT_SSE_HEARTBEAT_SECONDS = 15.0


def _latest_user_message_text(messages: list[dict[str, Any]]) -> str:
    """Return the latest user prompt for request-aware UI recovery."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else str(content or "")
    return ""


# 自動承認で実行済みの書き込みがあるか。取り消せない変更なので、そのカードは必ず残す。
# Whether an auto-approved write already ran; that change cannot be undone, so its card stays.
def _has_executed_approval(approval_cards: Sequence[dict[str, Any]]) -> bool:
    return any(card.get("decision") == "auto" for card in approval_cards)


# 承認カードを本文・画像の後ろに付ける。カードがある回答では、利用者の判断をカードに一本化する
# ため選択ボタンを外す。
# Append approval cards after the body and images. A reply carrying cards drops its choice
# buttons so the user decides in one place, the card.
def _with_tool_approval_parts(
    message_parts: list[dict[str, Any]] | None,
    text: str,
    approval_cards: Sequence[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    if not approval_cards:
        return message_parts
    base_parts = message_parts if message_parts else ([{"type": "text", "text": text}] if text else [])
    return [
        *(part for part in base_parts if part.get("type") != INTERACTIVE_BUTTONS_PART_TYPE),
        *(tool_approval_part(card) for card in approval_cards),
    ]


# 生成ジョブ1件の状態と、イベント配信・保存・停止を持つ基底クラス
# Base class holding one generation job's state, event delivery, persistence and stopping
class ChatGenerationJobBase:
    # ジョブを初期化する
    # Initialize the job
    def __init__(
        self,
        *,
        conversation_messages: list[dict[str, Any]],
        model: str,
        persist_response: Callable[..., dict[str, Any] | None],
        locale: str = "ja",
        on_finished: Callable[[], None] | None = None,
        on_event: Callable[[ChatGenerationEvent], None] | None = None,
        on_error: Callable[[], None] | None = None,
        prior_web_search_results: list[WebSearchResult] | None = None,
        pasted_url_pages: Sequence[PastedUrlPage] = (),
        earlier_pasted_urls: Sequence[str] = (),
        is_cancel_requested: Callable[[], bool] | None = None,
        personal_knowledge_search: Callable[[str], dict[str, Any]] | None = None,
        shared_prompt_search: Callable[[str], dict[str, Any]] | None = None,
        selected_reference_trace: list[SelectedReferenceLookupTrace] | None = None,
        ui_mode: GenerativeUiMode | str | None = None,
        explicit_ui_opt_out: bool = False,
        renew_active_job_lock: Callable[[], bool] | None = None,
        renew_active_job_lock_interval_seconds: float = 0.0,
        workspace_tools: ChatWorkspaceToolbox | None = None,
    ) -> None:
        self._conversation_messages = [dict(message) for message in conversation_messages]
        self._model = model
        self._locale = normalize_locale(locale, default="ja") or "ja"
        self._ui_mode = ui_mode
        # 判定モデルの NONE ではなく、ユーザー自身がUI不要と書いた場合だけ検証済み
        # Artifact を破棄してよい。
        # Only a refusal the user wrote may discard a validated artifact; a classifier's
        # NONE may not.
        self._explicit_ui_opt_out = explicit_ui_opt_out
        # 生成UIの結果は SSE と履歴の両方へ同じ語彙で返す。失敗が無言で消える経路を残さない。
        # The generated-UI outcome is returned to SSE and history in one vocabulary so no
        # failure disappears silently.
        self._artifact_status_payload: dict[str, str] | None = None
        self._prior_web_search_results = list(prior_web_search_results or [])
        # 発話に貼られたURLの取得済み本文。ターン開始時に根拠として登録し、read_web_page が
        # 再取得なしで分割して読めるようにする。
        # Bodies already fetched for URLs pasted in the message. They are registered as
        # evidence at turn start so read_web_page pages through them without fetching again.
        self._pasted_url_pages = tuple(pasted_url_pages or ())
        # 過去ターンで貼られたURL。本文は持たず入口だけ登録し、モデルが必要としたときに
        # read_web_page が取りに行く。毎ターン先読みで取得しないのは待ち時間と通信を避けるため。
        # URLs pasted in earlier turns. Only the entry point is registered, with no body: the
        # fetch happens inside read_web_page if the model asks, so no turn pays for it upfront.
        self._earlier_pasted_urls = tuple(earlier_pasted_urls or ())
        # メモ/マイコンテキスト検索。ユーザーIDに束ねた呼び出し側のクロージャを受け取るので、
        # ジョブ自身はセッションもDBも知らないままでいられる。None のときは機能そのものが無効。
        # Memo / My Context lookup. The caller passes a closure already bound to a user id, so the
        # job stays free of session and database concerns. None means the feature is off.
        self._personal_knowledge_search = personal_knowledge_search
        # 公開プロンプト検索。公開データなので未ログインでも渡せる。None のときは無効。
        # Public prompt lookup. The data is public, so guests can have it too; None means off.
        self._shared_prompt_search = shared_prompt_search
        self._selected_reference_trace = list(selected_reference_trace or [])
        # 利用者のデータ（メモなど）を読み書きするツール。書き込みは承認カードを経由する。
        # None のときは機能そのものが無効（ゲスト・一時ルーム・既定スキルが OFF）。
        # Tools that read and write the user's data (memos and so on); writes go through
        # approval cards. None means the feature is off (guest, temporary room, Skill off).
        self._workspace_tools = workspace_tools
        self._workspace_tool_runner = (
            WorkspaceToolRunner(workspace_tools, publish=self._publish) if workspace_tools is not None else None
        )
        # このターンで作った承認カード。停止時にも保存できるよう、ターン状態と同じリストを共有する。
        # Approval cards made this turn, shared with the turn state so a stop can still save them.
        self._tool_approval_parts: list[dict[str, Any]] = []
        self._persist_response = persist_response
        self._on_finished = on_finished
        self._on_finished_called = False
        self._on_event = on_event
        self._on_error = on_error
        # 他プロセスからの停止要求を拾うためのフック。Pub/Sub 通知を取りこぼしても
        # このポーリングで最終的に停止できるようにしておく。
        # Hook for stop requests raised by another process. Polling here guarantees the job
        # still stops even if the pub/sub notification is missed.
        self._is_cancel_requested = is_cancel_requested
        self._next_cancel_check_at = 0.0
        self._events: list[ChatGenerationEvent] = []
        self._next_sequence_id = 1
        self._condition = threading.Condition()
        self._future: Future[None] | None = None
        self._cancelled: bool = False
        # 生成途中で停止された場合でも保存できるよう、出力済みチャンクを保持する。
        # Keep emitted chunks so a mid-stream stop can still persist the partial reply.
        self._chunks: list[str] = []
        # ツール呼び出しの有無が確定するまでの一時チャンク。キャンセル時だけ部分応答として使う。
        # Buffer the current model step until tool-call presence is known; use it as a partial
        # response only when the user cancels generation.
        self._pending_stream_chunks: list[str] = []
        # `_chunks` / `_pending_stream_chunks` の読み書きを、生成スレッドと停止経路
        # （リクエストスレッドの cancel()）の間で排他制御する。cancel() が内側で
        # `_take_pending_answer_text()` を呼ぶため再入可能な RLock にしている。
        # Guards reads/writes of `_chunks` / `_pending_stream_chunks` between the generation
        # thread and the stop path (cancel() on the request thread). An RLock is used because
        # cancel() calls `_take_pending_answer_text()` while already holding it.
        self._chunks_lock = threading.RLock()
        # 調査の締めステップなど、ユーザー向け本文にならない一時バッファであることの印。
        # Marks a pending buffer that is internal-only and must never be saved as the answer.
        self._pending_stream_is_internal = False
        # 継続中に全文を書き直しているかどうか。停止時は全文をそのまま足さず接合する。
        # Whether a continuation is rewriting the full answer; cancellation must splice it.
        self._pending_stream_is_rewrite = False
        # 直前のモデルストリームが出力上限で打ち切られたか。回答なら継続生成へ回す。
        # Whether the last model stream was cut off by the output cap; an answer then
        # continues instead of being persisted as if the model had finished.
        self._last_stream_output_limited = False
        # Search-image selections are made as soon as search results arrive so a
        # cancellation can still persist images that were already revealed.
        self._selected_web_search_images: list[dict[str, str]] = []
        self._finalize_lock = threading.Lock()
        self._response_persisted = False
        # アクティブジョブロックのTTLを定期更新するための設定とスレッド。
        # トークンが無い（Redis未使用）場合は更新スレッドを起動しない。
        # Settings and thread for periodically renewing the active-job lock's TTL.
        # No renewal thread starts when there is no token (Redis unused).
        self._renew_active_job_lock = renew_active_job_lock
        self._renew_active_job_lock_interval_seconds = max(
            float(renew_active_job_lock_interval_seconds), 0.0
        )
        self._lock_renewal_thread: threading.Thread | None = None
        self._lock_renewal_stop_event = threading.Event()
        # 1ターン分の生成テレメトリ。長いステップのターンで「短い（不足生成）」と
        # 「切れた（打ち切り）」を運用ログから切り分けるために集計する。
        # Per-turn telemetry so operations can separate under-generation from truncation on
        # long, many-step turns straight from the structured logs.
        self._telemetry = ChatGenerationTelemetry(model=model)
        self.response = ""
        self.error_message: str | None = None
        self.started_at = time.monotonic()
        self.finished_at: float | None = None
        self.is_done = False

    # 生成された最終応答とUIパーツ情報を永続化（データベース等へ保存）する
    # Persist the final generated response and UI parts info (save to database, etc.)
    def _persist_generated_response(
        self,
        response: str,
        message_parts: list[dict[str, Any]] | None,
        web_search_context: list[dict[str, Any]] | None = None,
        tool_approval_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        try:
            signature = inspect.signature(self._persist_response)
            parameters = signature.parameters
            has_var_keyword = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            accepts_message_parts = "message_parts" in parameters or has_var_keyword
            accepts_web_search_context = (
                "web_search_context" in parameters or has_var_keyword
            )
            accepts_tool_approval_ids = "tool_approval_ids" in parameters or has_var_keyword
        except (TypeError, ValueError):
            accepts_message_parts = False
            accepts_web_search_context = False
            accepts_tool_approval_ids = False

        kwargs: dict[str, Any] = {}
        if accepts_message_parts:
            kwargs["message_parts"] = message_parts
        if accepts_web_search_context and web_search_context:
            kwargs["web_search_context"] = web_search_context
        # 承認行は回答の保存と同じトランザクションで回答へ結び付ける。結び付くまで承認 API は
        # その行を受け付けない。
        # Approval rows are tied to the reply in the same transaction that saves it; until then
        # the approval API refuses them.
        if accepts_tool_approval_ids and tool_approval_ids:
            kwargs["tool_approval_ids"] = tool_approval_ids
        return self._persist_response(response, **kwargs)

    # 応答の永続化を一度だけ実行する（完了とキャンセルの二重保存を防ぐ）
    # Persist the response at most once (avoid double-saving on completion vs. cancel)
    def _persist_once(
        self,
        response: str,
        message_parts: list[dict[str, Any]] | None,
        web_search_context: list[dict[str, Any]] | None = None,
        approval_cards: Sequence[dict[str, Any]] = (),
    ) -> dict[str, Any] | None:
        with self._finalize_lock:
            if self._response_persisted:
                return None
            self._response_persisted = True
        return self._persist_generated_response(
            response,
            message_parts,
            web_search_context=web_search_context,
            tool_approval_ids=[str(card["id"]) for card in approval_cards],
        )

    # ジョブの非同期処理をスレッドプール上で開始する
    # Start the job's asynchronous processing in the thread pool
    def start(self) -> None:
        if self._future is not None:
            return
        # 生成ジョブ専用プールへ投入する。空き枠が無ければ ChatGenerationCapacityError が
        # 送出され、呼び出し元（start_generation_job）がそのまま呼び出し元へ伝える。
        # Submit to the generation-only pool; a full pool raises ChatGenerationCapacityError,
        # which start_generation_job simply lets propagate to its caller.
        self._future = submit_generation_task(self._run)
        if self._renew_active_job_lock is not None and self._renew_active_job_lock_interval_seconds > 0:
            thread = threading.Thread(
                target=self._run_lock_renewal_loop,
                name="chat-generation-lock-renewal",
                daemon=True,
            )
            self._lock_renewal_thread = thread
            thread.start()

    # アクティブジョブロックのTTLを、所有トークンを確認しながら定期更新するループ。
    # ジョブが完了したら（`_mark_done` が停止イベントを立てて）即座に抜ける。
    # Loop that periodically renews the active-job lock's TTL while checking the owner
    # token. It exits as soon as the job finishes (`_mark_done` sets the stop event).
    def _run_lock_renewal_loop(self) -> None:
        renew = self._renew_active_job_lock
        if renew is None:
            return
        interval = self._renew_active_job_lock_interval_seconds
        while not self._lock_renewal_stop_event.wait(timeout=interval):
            if self.is_done:
                return
            try:
                renewed = renew()
            except Exception:
                logger.exception("Failed to renew the active chat generation job lock.")
                continue
            if not renewed:
                # 他ワーカーがロックを奪った、またはRedis障害で確認できなかった場合。
                # ここでジョブを止めることはしない（フェイルクローズは新規開始側の
                # try_acquire_active_job_lock が担う）が、運用ログには残す。
                # Another worker took the lock, or a Redis outage made this unverifiable.
                # This does not stop the job here (fail-closed admission is enforced by
                # try_acquire_active_job_lock on new starts); just record it for operators.
                logger.warning(
                    "Could not renew the active chat generation job lock; "
                    "it may have expired or been taken over by another worker."
                )

    # ジョブの実行をキャンセルし、生成途中のテキストを保存して abortedイベントを発行する
    # Cancel the job, persist any partial text, and publish an aborted event
    def cancel(self) -> None:
        # 生成をキャンセルし、aborted イベントを発行して完了とする。
        # ここまでに生成されたテキストがあれば保存し、停止後も残るようにする。
        # Cancel generation and mark it complete with an aborted event.
        # If any text was produced before the stop, persist it so it is not lost.
        if self.is_done:
            return
        self._cancelled = True

        # 取り出し・追記・読み取りをひとつの排他区間にまとめる。生成スレッド側の
        # `_publish_completed_answer_step` も同じロックの下で `_cancelled` を見てから
        # 追記するため、ここで確定した partial_text と生成スレッドの通常経路の保存が
        # 二重に本文を積むことはない。
        # Take, append and read as one critical section. The generation thread's own
        # `_publish_completed_answer_step` checks `_cancelled` under the same lock before
        # appending, so the partial_text finalized here and the generation thread's normal
        # save path can never both commit the same text.
        with self._chunks_lock:
            pending_text = self._take_pending_answer_text()
            if pending_text:
                self._chunks.append(pending_text)
            partial_text = "".join(self._chunks)
            if self._workspace_tools is not None:
                fallback = _unconfirmed_write_claim_fallback(
                    partial_text,
                    _latest_user_message_text(self._conversation_messages),
                    self._tool_approval_parts,
                )
                if fallback is not None:
                    self._chunks[:] = [fallback]
                    partial_text = fallback
                    pending_text = fallback
        if pending_text:
            self._publish("chunk", {"text": pending_text})
        approval_cards = self._settle_approvals_after_interruption()
        # 自動承認で実行済みの書き込みは取り消せないので、本文が無くてもカードを残す。
        # A write already run through auto approval cannot be undone, so its card is kept even
        # without body text.
        if not partial_text.strip() and not _has_executed_approval(approval_cards):
            # まだ本文が無い場合は空応答を保存せず、中断のみ通知する。
            # No body yet: skip persisting an empty reply and only signal the abort.
            self._publish("aborted", {}, done=True)
            return

        normalized_response = normalize_response_with_artifacts(
            partial_text,
            recover_truncated=True,
            ui_mode=self._ui_mode,
            explicit_ui_opt_out=self._explicit_ui_opt_out,
        )
        bot_reply = normalized_response.text
        message_parts = normalized_response.parts
        if self._selected_web_search_images:
            message_parts = attach_web_search_images_to_artifacts(
                message_parts,
                self._selected_web_search_images,
            )
            message_parts = append_web_search_image_parts(
                message_parts,
                self._selected_web_search_images,
                fallback_text=bot_reply,
            )
            if message_parts:
                message_parts = normalize_message_parts_for_display(message_parts) or None
        message_parts = _with_tool_approval_parts(message_parts, bot_reply, approval_cards)
        self.response = bot_reply

        persist_metadata: dict[str, Any] | None = None
        try:
            persist_metadata = self._persist_once(bot_reply, message_parts, approval_cards=approval_cards)
        except Exception:
            logger.exception("Failed to persist partial chat response on cancel.")

        aborted_payload: dict[str, Any] = {"response": bot_reply, "partial": True}
        if message_parts:
            aborted_payload["parts"] = message_parts
        if isinstance(persist_metadata, dict):
            aborted_payload.update(persist_metadata)
        self._publish("aborted", aborted_payload, done=True)

    # 停止・失敗したターンの承認カードを確定する。未実行の承認待ちは取り消し、カードも合わせる。
    # Settle the approval cards of a stopped or failed turn: pending ones are cancelled, and the
    # cards follow.
    def _settle_approvals_after_interruption(self) -> list[dict[str, Any]]:
        if self._workspace_tool_runner is None or not self._tool_approval_parts:
            return list(self._tool_approval_parts)
        settled = self._workspace_tool_runner.settle_after_interruption(list(self._tool_approval_parts))
        self._tool_approval_parts[:] = settled
        return settled

    # 未配信バッファを本文として取り出し、バッファを空にする。
    # 停止も失敗も「モデルが書いたのに配信していない本文」を抱えたまま終わるため、
    # 取り出し方（内部メモの除去・書き直しの接合・境界重複の除去）は1か所に置く。
    # Take the undelivered buffer as body text and empty it. A stop and a failure both end
    # while holding text the model wrote but the turn never published, so how it is taken —
    # stripping internal notes, splicing a rewrite, removing boundary overlap — lives here.
    def _take_pending_answer_text(self) -> str:
        # `_chunks_lock` は再入可能。cancel() が既に保持したまま呼んでも、生成スレッドから
        # 単独で呼んでも安全にする。
        # `_chunks_lock` is reentrant so this is safe whether cancel() already holds it or
        # the generation thread calls this on its own.
        with self._chunks_lock:
            if not self._pending_stream_chunks or self._pending_stream_is_internal:
                return ""
            # 調査ステップの途中で終わった場合、内部メモが本文として残らないよう取り除く。
            # An end during a research step must not leave internal notes in the saved body.
            pending_text = strip_turn_state_update("".join(self._pending_stream_chunks))
            # タグを落とした封筒 JSON だけが残っていても、それは回答ではない。
            # An envelope JSON that lost its tags is not an answer either.
            if self._untagged_turn_state_update(self._pending_stream_chunks, pending_text) is not None:
                self._telemetry.untagged_turn_state_recoveries += 1
                self._pending_stream_chunks = []
                self._pending_stream_is_rewrite = False
                return ""
            existing_text = "".join(self._chunks)
            # 競合で書き直しフラグを読む前に停止しても、既存本文の末尾を先に錨として
            # 探す。通常の継続の境界重複にも同じ処理が効き、短い本文だけは従来の窓で補う。
            # Use the existing tail as an anchor even if cancellation races the rewrite-mode
            # flag. The same splice handles normal boundary overlap; the window covers short text.
            should_splice = self._pending_stream_is_rewrite or looks_like_restarted_answer(
                existing_text,
                pending_text,
            )
            if should_splice:
                spliced_pending = splice_restarted_answer(existing_text, pending_text)
                # 書き直しを接合できない場合は本文を丸ごと捨て、二重化を優先して防ぐ。
                # If a rewrite cannot be spliced, drop it rather than duplicating the answer.
                pending_text = spliced_pending if spliced_pending is not None else ""
            else:
                pending_text = strip_continuation_overlap(existing_text, pending_text)
            self._pending_stream_chunks = []
            self._pending_stream_is_rewrite = False
        return pending_text

    # タグ付きの封筒が読めず、除去後の本文がタグの無い封筒 JSON だけならその内容を返す。
    # Return the update when no tagged envelope was readable and the stripped body is only an
    # untagged envelope JSON.
    def _untagged_turn_state_update(self, chunks: list[str], visible_text: str) -> dict[str, Any] | None:
        if not visible_text or parse_turn_state_update(chunks) is not None:
            return None
        return parse_bare_turn_state_update(
            visible_text,
            latest_user_message=_latest_user_message_text(self._conversation_messages),
        )

    # 自プロセス・他プロセスのいずれかから停止が要求されたかを判定する
    # Report whether a stop was requested from this process or from another one
    def _should_stop(self) -> bool:
        if self._cancelled:
            return True
        if self._is_cancel_requested is None:
            return False

        # 停止要求の確認は外部ストア参照になるため、一定間隔に間引く。
        # Checking the stop request hits an external store, so throttle it.
        now = time.monotonic()
        if now < self._next_cancel_check_at:
            return False
        self._next_cancel_check_at = now + REMOTE_CANCEL_CHECK_INTERVAL_SECONDS

        try:
            requested = bool(self._is_cancel_requested())
        except Exception:
            logger.exception("Failed to check remote chat generation cancel request.")
            return False
        if requested:
            self.cancel()
        return self._cancelled

    # ジョブスレッドの完了を待機する
    # Wait for the job thread to complete
    def wait(self, timeout: float | None = None) -> bool:
        future = self._future
        if future is None:
            return self.is_done
        try:
            future.result(timeout=timeout)
        except TimeoutError:
            return self.is_done
        except Exception:
            # 日本語: 待機対象のタスクが失敗しても完了状態の返却は続けます。原因追跡のため記録します。
            # English: Keep returning the completion state even when the awaited task failed; record why.
            logger.debug("Waiting for the generation task failed.", exc_info=True)
            return self.is_done
        return self.is_done

    # 生成中のイベントを発生順にストリーミング（イテレート）する
    # Stream (iterate) generation events in chronological order
    def iter_events(
        self,
        *,
        after_sequence_id: int = 0,
        heartbeat_seconds: float = DEFAULT_SSE_HEARTBEAT_SECONDS,
    ) -> Iterator[ChatGenerationEvent | None]:
        cursor = 0
        heartbeat_interval = max(float(heartbeat_seconds), 0.0)
        next_heartbeat_at = time.monotonic() + heartbeat_interval
        while True:
            heartbeat_due = False
            with self._condition:
                while (
                    cursor < len(self._events)
                    and self._events[cursor].sequence_id <= after_sequence_id
                ):
                    cursor += 1

                while cursor >= len(self._events) and not self.is_done:
                    wait_timeout = 0.5
                    if heartbeat_interval:
                        wait_timeout = min(
                            wait_timeout,
                            max(next_heartbeat_at - time.monotonic(), 0.0),
                        )
                    self._condition.wait(timeout=wait_timeout)
                    if (
                        heartbeat_interval
                        and cursor >= len(self._events)
                        and not self.is_done
                        and time.monotonic() >= next_heartbeat_at
                    ):
                        heartbeat_due = True
                        next_heartbeat_at = time.monotonic() + heartbeat_interval
                        break

                if heartbeat_due:
                    event = None
                elif cursor < len(self._events):
                    event = self._events[cursor]
                    cursor += 1
                    next_heartbeat_at = time.monotonic() + heartbeat_interval
                elif self.is_done:
                    break
                else:
                    continue

            yield event

    # 新しいイベントを発行し、待機スレッドおよび分散イベントチャネルに通知する
    # Publish a new event, notifying waiting threads and distributed event channels
    def _publish(self, event: str, payload: dict[str, Any], *, done: bool = False) -> None:
        callback: Callable[[], None] | None = None
        event_callback = self._on_event
        published_event: ChatGenerationEvent | None = None
        with self._condition:
            if self.is_done:
                return
            sequence_id = self._next_sequence_id
            self._next_sequence_id += 1
            published_event = ChatGenerationEvent(
                sequence_id=sequence_id,
                event=event,
                payload=payload,
            )
            self._events.append(published_event)
            if done:
                callback = self._mark_done()
            self._condition.notify_all()
        if event_callback is not None and published_event is not None:
            try:
                event_callback(published_event)
            except Exception:
                logger.exception("Failed to publish distributed chat generation event.")
        if callback is not None:
            callback()

    # ジョブの状態を「完了」にマークする
    # Mark the job status as done
    def _mark_done(self) -> Callable[[], None] | None:
        if self.is_done:
            return None
        self.is_done = True
        self.finished_at = time.monotonic()
        # ロック更新スレッドが最大 interval 秒も無駄に生き残らないよう、完了と同時に起こす。
        # Wake the lock-renewal thread immediately instead of letting it linger up to
        # one interval after completion.
        self._lock_renewal_stop_event.set()
        if self._on_finished_called or self._on_finished is None:
            return None
        self._on_finished_called = True
        return self._on_finished

    # エラー情報を設定し、後片付けを終えてから errorイベントを発行してジョブを終了する
    # Set error details, finish cleanup, then publish an error event and terminate the job
    def _handle_error(
        self,
        message: str,
        payload: dict[str, Any],
        *,
        invoke_error_callback: bool = False,
    ) -> None:
        localized_message = translate_text(message, self._locale)
        self.error_message = localized_message
        payload = {**payload, "message": localized_message}
        # 後片付けは done=True の配信より前に完了させる。SSE の消費側は終端イベントを
        # 受け取った時点で履歴の再取得などへ進むため、順序が逆だと未回答のユーザー発話が
        # まだ残った状態を読んでしまう。
        # Finish cleanup before publishing the terminal (done=True) event. SSE consumers move
        # on — reloading history, for instance — as soon as they see the stream end, so the
        # reverse order lets them observe a user message the cleanup has not discarded yet.
        self._run_error_callback(invoke_error_callback)
        self._publish("error", payload, done=True)

    # エラーコールバックを実行する。失敗してもエラーイベントの配信は止めない。
    # Run the error callback; a failure here must never block the error event.
    def _run_error_callback(self, invoke_error_callback: bool) -> None:
        if not invoke_error_callback or self._on_error is None:
            return
        try:
            self._on_error()
        except Exception:
            # 握りつぶさずログへ残す。掃除に失敗してもユーザーへはエラーを届ける。
            # Log instead of swallowing silently: the user still gets the error event.
            logger.exception("Failed to run chat generation error callback.")

    # キャンセルを監視しながら、指定された秒数待機（スリープ）する
    # Sleep for a specified duration while monitoring for cancellation
    def _sleep_with_cancel(self, delay: float) -> bool:
        deadline = time.monotonic() + max(delay, 0.0)
        while time.monotonic() < deadline:
            if self._cancelled:
                return True
            time.sleep(min(0.1, max(deadline - time.monotonic(), 0.0)))
        return self._cancelled
