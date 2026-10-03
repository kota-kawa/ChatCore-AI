from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from fastapi import Request

from services.generative_ui import GenerativeUiMode

from .chat_generation_agent_loop import ChatGenerationAgentLoopMixin
from .chat_generation_answer_stream import ChatGenerationAnswerStreamMixin
from .chat_generation_coordinator import (
    ChatGenerationCoordinator,
    ChatGenerationEvent,
    # blueprints が `services.chat_generation` から直接 import しているため再エクスポートする。
    # Re-exported because the blueprints import it straight from `services.chat_generation`.
    ChatGenerationStreamTimeoutError,  # noqa: F401
)
from .chat_generation_executor import (
    # chat_use_case / chat_regeneration_pipeline が `services.chat_generation` から直接
    # import しているため再エクスポートする。
    # Re-exported because chat_use_case / chat_regeneration_pipeline import it straight
    # from `services.chat_generation`.
    ChatGenerationCapacityError,  # noqa: F401
)
from .chat_generation_finalization import ChatGenerationFinalizationMixin
from .chat_generation_job_base import DEFAULT_SSE_HEARTBEAT_SECONDS
from .chat_generation_llm_stream import ChatGenerationLlmStreamMixin
from .chat_generation_tools import ChatGenerationToolsMixin
from .chat_generation_turn import ChatTurnRunState
from .chat_generation_web_search import ChatGenerationWebSearchMixin
from .chat_url_context import PastedUrlPage
from .chat_workspace_tools.registry import ChatWorkspaceToolbox
from .selected_reference_context import SelectedReferenceLookupTrace
from .web_search import WebSearchResult

logger = logging.getLogger(__name__)

JOB_RETENTION_SECONDS = 300
DEFAULT_ACTIVE_JOB_LOCK_TTL_SECONDS = 900
# アクティブジョブロックのTTLをこの分数ごとに更新する。3分割にしておけば、更新が
# 1回落ちても次の再試行がTTL切れ前に間に合う。
# Renew the active-job lock at this fraction of its TTL. Splitting it into thirds gives a
# missed renewal one more attempt before the TTL actually expires.
ACTIVE_JOB_LOCK_RENEWAL_TTL_FRACTION = 3
DEFAULT_DISTRIBUTED_STREAM_IDLE_TIMEOUT_SECONDS = 60
# 停止要求が別ワーカーへ届いた場合に、所有ワーカーの応答を待つ上限。
# Upper bound for waiting on the owning worker after a stop request lands on another worker.
DEFAULT_REMOTE_CANCEL_TIMEOUT_SECONDS = 5.0


# 同一の部屋・ユーザーで既に生成ジョブが実行中である場合に投げられる例外クラス
# Exception class raised when a generation job is already running for the same room/user
class ChatGenerationAlreadyRunningError(RuntimeError):
    pass


# 個別のチャット応答生成のバックグラウンドタスクおよびイベントを管理するクラス
# Class that manages the background task and events for a single chat response generation
# 状態・配信・停止は ChatGenerationJobBase、生成ループの各フェーズは Mixin が持ち、
# このクラスはそれらを束ねて `_run` で順に呼ぶ。
# ChatGenerationJobBase holds the state, delivery and stopping; the mixins hold the phases of
# the generation loop. This class assembles them and sequences the phases in `_run`.
class ChatGenerationJob(
    ChatGenerationFinalizationMixin,
    ChatGenerationAgentLoopMixin,
    ChatGenerationToolsMixin,
    ChatGenerationWebSearchMixin,
    ChatGenerationAnswerStreamMixin,
    ChatGenerationLlmStreamMixin,
):
    # バックグラウンドスレッドで実行されるチャット応答生成の入口。各フェーズを順に呼ぶだけ。
    # Entry point of chat response generation on the background thread; it only sequences phases.
    def _run(self) -> None:
        # ターン状態の構築も含めて守る。ここで落ちると state が無いままになるため、
        # 終端イベントは finally 側の保険が出す。
        # The turn-state construction is guarded too. A failure there leaves no state, so the
        # terminal event comes from the safety net in `finally`.
        state: ChatTurnRunState | None = None
        try:
            state = self._build_turn_run_state()
            if self._should_stop():
                return

            self._configure_agent_tools(state)
            if self._run_agent_loop(state):
                return
            self._flush_streaming_citation_buffer(state)

            if self._should_stop():
                return

            # 仕上げ（正規化・引用解決・保存）も同じ try の中で守る。ここで例外が
            # 抜けると終端イベントが出ず、SSE は終わらず生成ロックも解放されない。
            # Finalization (normalization, citation resolution, persistence) is guarded by the
            # same try. An exception escaping here would publish no terminal event, leaving the
            # SSE stream open and the generation lock held.
            self._finalize_generation(state)

        # エラーハンドリング
        # ユーザーへエラーを表示する経路は必ずログにも詳細を残す方針のため、各分岐で
        # exc_info 付きのログを出す（呼び出し元の llm.py 側で既にログ済みの例外でも、
        # ここでは会話ターンのテレメトリ（モデル・ステップ数・調査有無など）を紐付けて
        # 再度記録し、どのターンで失敗したかを追えるようにする）。
        # Error handling. Every branch that surfaces an error to the user must also leave a
        # detailed log entry. Even though llm.py already logs the raw provider exception, log
        # again here with this turn's telemetry (model, step count, whether research/tool use
        # was in progress) so failures mid-loop (research → web search → answer) are traceable
        # to the specific turn, not just the provider call.
        except Exception as exc:
            if state is None:
                logger.exception(
                    "Failed to prepare the chat generation turn.",
                    extra=self._telemetry.as_log_extra(),
                )
            elif not self._finalize_failed_turn(exc, state):
                self._report_generation_failure(exc, state)
        finally:
            # どの経路を通っても終端イベントは必ず1つ出す。出さないまま抜けると
            # ジョブが done にならず、SSE の待ち受けと生成ロックが残り続ける。
            # Exactly one terminal event on every path. Leaving without one keeps the job
            # unfinished, so the SSE reader and the generation lock both hang on.
            self._ensure_terminal_event()

    # 終端イベントを一度も出していないジョブを、必ずエラーで締めるフェーズ。
    # The phase that closes any job which never published a terminal event.
    def _ensure_terminal_event(self) -> None:
        if self.is_done:
            return
        logger.error(
            "Chat generation ended without a terminal event; closing it as an error.",
            extra=self._telemetry.as_log_extra(),
        )
        error_message = "内部エラーが発生しました。"
        self._handle_error(
            error_message,
            {"message": error_message, "retryable": True},
            invoke_error_callback=not self._chunks,
        )


# ジェネレーションキーをビルドする関数
# Function to build the generation key
def build_generation_key(*, chat_room_id: str, user_id: int | None = None, sid: str | None = None) -> str:
    # 同じ room_id でもログインユーザーとゲストセッションは別の生成ジョブとして扱う。
    # これによりゲストの sid とユーザーIDの衝突や、共有 room_id による生成ロックの混線を防ぐ。
    # Treat logged-in users and guest sessions as different generation jobs even for the same room_id.
    # This prevents collisions between guest sids and user IDs, or crosstalk on generation locks due to shared room_ids.
    if user_id is not None:
        return f"user:{user_id}:{chat_room_id}"
    if sid is not None:
        return f"guest:{sid}:{chat_room_id}"
    raise ValueError("Either user_id or sid is required to build a generation key.")


# チャット生成サービスを定義するクラス
# Class defining the Chat Generation Service
class ChatGenerationService:
    # チャット応答生成ジョブを管理し、SSE の再接続・分散配信を吸収する。
    # ローカルプロセス内では `_jobs` にジョブを保持し、Redis が使える環境では
    # イベント履歴とアクティブロックを Redis にも書く。これにより、ロードバランサ配下で
    # 再接続先プロセスが変わっても、完了済み/実行中イベントを再生できる。
    #
    # Manages chat response generation jobs, smoothing over SSE reconnections and distributed delivery.
    # Keeps jobs in `_jobs` in the local process, and also writes event history and active locks to Redis
    # when available. This allows replaying completed/in-progress events even if the reconnected process
    # changes behind a load balancer.

    # サービスを初期化する
    # Initialize the service
    def __init__(
        self,
        *,
        job_retention_seconds: int = JOB_RETENTION_SECONDS,
        active_job_lock_ttl_seconds: int = DEFAULT_ACTIVE_JOB_LOCK_TTL_SECONDS,
        distributed_stream_idle_timeout_seconds: float = (
            DEFAULT_DISTRIBUTED_STREAM_IDLE_TIMEOUT_SECONDS
        ),
        sse_heartbeat_seconds: float = DEFAULT_SSE_HEARTBEAT_SECONDS,
        remote_cancel_timeout_seconds: float = DEFAULT_REMOTE_CANCEL_TIMEOUT_SECONDS,
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._job_retention_seconds = job_retention_seconds
        self._active_job_lock_ttl_seconds = max(active_job_lock_ttl_seconds, 1)
        # ジョブが生きている限りTTLを更新し続けるので、TTL自体はターンの壁時計上限では
        # なく「応答不能になったワーカーの掃除まで待つ時間」として機能する。
        # As long as the job is alive its TTL keeps getting renewed, so the TTL itself is not
        # a wall-clock cap on the turn; it only bounds how long a dead worker's lock lingers.
        self._active_job_lock_renew_interval_seconds = max(
            self._active_job_lock_ttl_seconds / ACTIVE_JOB_LOCK_RENEWAL_TTL_FRACTION,
            1.0,
        )
        self._distributed_stream_idle_timeout_seconds = max(
            float(distributed_stream_idle_timeout_seconds),
            0.0,
        )
        self._sse_heartbeat_seconds = max(float(sse_heartbeat_seconds), 0.0)
        self._remote_cancel_timeout_seconds = max(float(remote_cancel_timeout_seconds), 0.0)
        self._redis_client_getter = redis_client_getter
        self._jobs: dict[str, ChatGenerationJob] = {}
        self._jobs_lock = threading.Lock()
        # プロセス間協調（Redis Pub/Sub・分散ロック・停止要求）は専用のコラボレータへ委譲する。
        # ローカルジョブの操作だけをコールバックとして渡し、ライフサイクルはこのクラスが持つ。
        # Cross-process coordination (pub/sub, the distributed lock, stop requests) is delegated
        # to a dedicated collaborator; only local job operations are handed to it as callbacks
        # so the job lifecycle stays here.
        self._coordinator = ChatGenerationCoordinator(
            job_retention_seconds=self._job_retention_seconds,
            active_job_lock_ttl_seconds=self._active_job_lock_ttl_seconds,
            distributed_stream_idle_timeout_seconds=self._distributed_stream_idle_timeout_seconds,
            sse_heartbeat_seconds=self._sse_heartbeat_seconds,
            remote_cancel_timeout_seconds=self._remote_cancel_timeout_seconds,
            cancel_local_job=self._cancel_local_job,
            has_running_local_jobs=self._has_running_local_jobs,
            redis_client_getter=redis_client_getter,
        )

    # Redis クライアントを取得する
    # Retrieve the Redis client
    def _get_redis_client(self) -> Any | None:
        return self._coordinator.get_redis_client()

    # Redis 経由で分散イベントを配信する（リストへの追記および Pub/Sub 発行）
    # Publish a distributed event via Redis (append to list and publish via Pub/Sub)
    def _publish_distributed_event(self, job_key: str, event: ChatGenerationEvent) -> None:
        self._coordinator.publish_event(job_key, event)

    # 指定したジョブキーに対して Redis アクティブジョブロックの取得を試みる
    # Attempt to acquire the Redis active job lock for the specified job key
    def _try_acquire_active_job_lock(self, job_key: str) -> tuple[bool, str | None]:
        return self._coordinator.try_acquire_active_job_lock(job_key)

    # 自分が取得した Redis アクティブジョブロックを解放する
    # Release the Redis active job lock that was acquired by this instance
    def _release_active_job_lock(self, job_key: str, lock_token: str | None) -> None:
        self._coordinator.release_active_job_lock(job_key, lock_token)

    # 自分が取得した Redis アクティブジョブロックのTTLを、所有トークンを確認しながら延長する
    # Extend the TTL of the Redis active job lock this instance owns, verifying the owner token
    def _refresh_active_job_lock(self, job_key: str, lock_token: str | None) -> bool:
        return self._coordinator.refresh_active_job_lock(job_key, lock_token)

    # 指定したジョブキーに対して Redis アクティブジョブロックが存在するか確認する
    # Check if a Redis active job lock exists for the specified job key
    def _has_distributed_active_lock(self, job_key: str) -> bool:
        return self._coordinator.has_active_lock(job_key)

    # 指定ジョブに対する停止要求マーカーが立っているかを確認する
    # Check whether a stop-request marker is set for the specified job
    def _is_remote_cancel_requested(self, job_key: str) -> bool:
        return self._coordinator.is_remote_cancel_requested(job_key)

    # 停止要求マーカーを削除する（新しい生成ジョブが古い要求で止まらないようにする）
    # Clear the stop-request marker so a new job is not aborted by a stale request
    def _clear_remote_cancel_request(self, job_key: str) -> None:
        self._coordinator.clear_remote_cancel_request(job_key)

    # プロセス内に実行中のジョブが残っているかを確認する
    # Check whether this process still holds a running job
    def _has_running_local_jobs(self) -> bool:
        with self._jobs_lock:
            return any(not job.is_done for job in self._jobs.values())

    # ローカルに保持しているジョブだけをキャンセルする
    # Cancel only the job held in this process
    def _cancel_local_job(self, job_key: str) -> bool:
        with self._jobs_lock:
            job = self._jobs.get(job_key)
        if job is None or job.is_done:
            return False
        job.cancel()
        return True

    # 停止要求を Pub/Sub で配信し、ジョブを所有するワーカーの停止完了を待つ
    # Broadcast the stop request and wait for the owning worker to release the lock
    def _request_remote_cancel(self, job_key: str) -> bool:
        return self._coordinator.request_remote_cancel(job_key)

    # 停止要求を購読するスレッドが起動していることを保証する
    # Ensure the thread subscribing to stop requests is running
    def _ensure_cancel_listener(self) -> None:
        self._coordinator.ensure_cancel_listener()

    # Redis が有効で分散ストリーミングに対応しているかを確認する
    # Check if Redis is enabled and supports distributed streaming
    def supports_distributed_streaming(self) -> bool:
        return self._coordinator.supports_distributed_streaming()

    # メモリ上のジョブ状態をリセットし、必要に応じて実行中ジョブをキャンセルする
    # Reset the in-memory job state and optionally cancel running jobs
    def reset_in_memory_state(self, *, cancel_running: bool = False) -> None:
        running_jobs: list[ChatGenerationJob] = []
        with self._jobs_lock:
            if cancel_running:
                running_jobs = [
                    job
                    for job in self._jobs.values()
                    if not job.is_done
                ]
            self._jobs.clear()

        for job in running_jobs:
            job.cancel()

    # 実行中のすべてのジョブが完了するのを待機する
    # Wait for all running jobs to complete
    def wait_for_running_jobs(self, *, timeout: float | None = None) -> bool:
        with self._jobs_lock:
            running_jobs = [job for job in self._jobs.values() if not job.is_done]

        if not running_jobs:
            return True

        deadline = None if timeout is None else time.monotonic() + timeout
        all_done = True
        for job in running_jobs:
            if deadline is None:
                waited = job.wait(timeout=None)
            else:
                remaining = max(deadline - time.monotonic(), 0.0)
                waited = job.wait(timeout=remaining)
            if not waited:
                all_done = False
        return all_done

    # 保存期間を過ぎて期限切れとなった完了済みジョブをメモリから削除する
    # Remove expired completed jobs from memory based on retention time
    def _cleanup_expired_jobs(self, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        expired_keys: list[str] = []

        with self._jobs_lock:
            for key, job in self._jobs.items():
                if not job.is_done or job.finished_at is None:
                    continue
                if current_time - job.finished_at >= self._job_retention_seconds:
                    expired_keys.append(key)

            for key in expired_keys:
                self._jobs.pop(key, None)

    # 指定ジョブをキャンセルし、キャンセルできたか否かを返す
    # Cancel the specified job and return whether the cancellation succeeded
    def cancel_generation_job(self, job_key: str) -> bool:
        if self._cancel_local_job(job_key):
            return True
        # 複数ワーカー構成では停止リクエストがジョブ非所有のワーカーに届くことがある。
        # その場合でもロックを解放しないと、ルームが生成中のまま再生成を拒否し続ける。
        # Under multiple workers the stop request can land on a worker that does not own the
        # job. Without this the lock survives and the room keeps rejecting regeneration.
        return self._request_remote_cancel(job_key)

    # 指定したジョブキーで現在生成処理が実行中であるか確認する
    # Check if a generation process is currently running for the specified job key
    def has_active_generation(self, job_key: str) -> bool:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            job = self._jobs.get(job_key)
            if job is not None:
                return not job.is_done
        return self._has_distributed_active_lock(job_key)

    # 再生可能な生成処理（メモリ上または Redis 上にイベントがある）が存在するか確認する
    # Check if a replayable generation process (with events in-memory or Redis) exists
    def has_replayable_generation(self, job_key: str) -> bool:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            local_job = self._jobs.get(job_key)
            if local_job is not None:
                return True

        return self._coordinator.has_replay_history(job_key)

    # 指定したジョブキーに対応するローカルジョブオブジェクトを取得する
    # Retrieve the local job object corresponding to the specified job key
    def get_generation_job(self, job_key: str) -> ChatGenerationJob | None:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            return self._jobs.get(job_key)

    # メモリまたは Redis Pub/Sub から生成イベントをイテレートして呼び出し元にストリームする
    # Iterate and stream generation events to the caller from memory or Redis Pub/Sub
    def iter_generation_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
    ) -> Iterator[ChatGenerationEvent | None]:
        job = self.get_generation_job(job_key)
        if job is not None:
            yield from job.iter_events(
                after_sequence_id=after_sequence_id,
                heartbeat_seconds=self._sse_heartbeat_seconds,
            )
            return

        # ローカルにジョブがない場合でも、Redis のイベント履歴があれば再接続として扱う。
        # これは複数プロセス構成で SSE 接続先が生成元と異なる場合に必要。
        # A job absent from this process is still a reconnection when Redis holds its event
        # history, which happens whenever the SSE connection lands on another worker.
        yield from self._coordinator.iter_distributed_events(
            job_key,
            after_sequence_id=after_sequence_id,
            has_active_generation=self.has_active_generation,
        )

    # 新しいチャット応答生成ジョブを開始する
    # Start a new chat response generation job
    def start_generation_job(
        self,
        job_key: str,
        *,
        conversation_messages: list[dict[str, Any]],
        model: str,
        persist_response: Callable[..., dict[str, Any] | None],
        locale: str = "ja",
        on_finished: Callable[[], None] | None = None,
        on_error: Callable[[], None] | None = None,
        prior_web_search_results: list[WebSearchResult] | None = None,
        pasted_url_pages: Sequence[PastedUrlPage] = (),
        earlier_pasted_urls: Sequence[str] = (),
        personal_knowledge_search: Callable[[str], dict[str, Any]] | None = None,
        shared_prompt_search: Callable[[str], dict[str, Any]] | None = None,
        selected_reference_trace: list[SelectedReferenceLookupTrace] | None = None,
        ui_mode: GenerativeUiMode | str | None = None,
        explicit_ui_opt_out: bool = False,
        workspace_tools: ChatWorkspaceToolbox | None = None,
    ) -> ChatGenerationJob:
        self._cleanup_expired_jobs()
        acquired_lock, lock_token = self._try_acquire_active_job_lock(job_key)
        if not acquired_lock:
            raise ChatGenerationAlreadyRunningError(job_key)

        # 直前のジョブに対する停止要求が残っていると新しいジョブが即座に止まるため消す。
        # Drop any leftover stop request so the new job is not aborted by the previous one.
        self._clear_remote_cancel_request(job_key)

        # Redis ロックを先に取り、次にプロセス内の `_jobs` を確認する。
        # 逆順だと別プロセスとの競合を検出できず、同じ room で二重生成が走りうる。
        with self._jobs_lock:
            existing_job = self._jobs.get(job_key)
            if existing_job is not None and not existing_job.is_done:
                self._release_active_job_lock(job_key, lock_token)
                raise ChatGenerationAlreadyRunningError(job_key)

            job = ChatGenerationJob(
                conversation_messages=conversation_messages,
                model=model,
                persist_response=persist_response,
                locale=locale,
                on_finished=lambda: self._finalize_job(
                    job_key,
                    lock_token,
                    on_finished=on_finished,
                ),
                on_event=lambda event: self._publish_distributed_event(job_key, event),
                on_error=on_error,
                prior_web_search_results=prior_web_search_results,
                pasted_url_pages=pasted_url_pages,
                earlier_pasted_urls=earlier_pasted_urls,
                is_cancel_requested=lambda: self._is_remote_cancel_requested(job_key),
                personal_knowledge_search=personal_knowledge_search,
                shared_prompt_search=shared_prompt_search,
                selected_reference_trace=selected_reference_trace,
                ui_mode=ui_mode,
                explicit_ui_opt_out=explicit_ui_opt_out,
                renew_active_job_lock=(
                    (lambda: self._refresh_active_job_lock(job_key, lock_token))
                    if lock_token is not None
                    else None
                ),
                renew_active_job_lock_interval_seconds=self._active_job_lock_renew_interval_seconds,
                workspace_tools=workspace_tools,
            )
            self._jobs[job_key] = job

        # 購読スレッドは `_jobs_lock` の外で起動する（ロック順序を固定して待ち合わせを避ける）。
        # Start the listener outside `_jobs_lock` to keep the lock ordering consistent.
        self._ensure_cancel_listener()

        try:
            job.start()
        except Exception:
            # start に失敗したジョブはリプレイ対象に残さず、分散ロックも即時解放する。
            with self._jobs_lock:
                self._jobs.pop(job_key, None)
            self._release_active_job_lock(job_key, lock_token)
            raise
        return job

    # ジョブを正常またはエラー終了後にクリーンアップ（ロック解放やコールバック実行）する
    # Clean up the job after normal or error completion (release lock, run callbacks)
    def _finalize_job(
        self,
        job_key: str,
        lock_token: str | None,
        *,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self._release_active_job_lock(job_key, lock_token)
        if on_finished is None:
            return
        try:
            on_finished()
        except Exception:
            logger.exception("Failed to run chat generation finished callback.")


_default_chat_generation_service = ChatGenerationService()


# アプリケーション状態またはデフォルトから ChatGenerationService のインスタンスを取得する
# Retrieve the ChatGenerationService instance from the application state or default
def get_chat_generation_service(request: Request = None) -> ChatGenerationService:
    if request is not None:
        app = request.scope.get("app")
        state = getattr(app, "state", None)
        service = getattr(state, "chat_generation_service", None)
        if isinstance(service, ChatGenerationService):
            return service
    return _default_chat_generation_service


# メモリ上のすべての生成ジョブの状態をクリアする
# Clear the state of all in-memory generation jobs
def clear_generation_job_state(*, cancel_running: bool = False) -> None:
    get_chat_generation_service().reset_in_memory_state(cancel_running=cancel_running)


# 指定したジョブをキャンセルする
# Cancel the specified job
def cancel_generation_job(
    job_key: str,
    *,
    service: ChatGenerationService | None = None,
) -> bool:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.cancel_generation_job(job_key)


# 指定したジョブで生成が進行中であるかを判定する
# Determine if a generation is currently active for the specified job
def has_active_generation(
    job_key: str,
    *,
    service: ChatGenerationService | None = None,
) -> bool:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.has_active_generation(job_key)


# 指定したジョブを取得する
# Retrieve the specified generation job
def get_generation_job(
    job_key: str,
    *,
    service: ChatGenerationService | None = None,
) -> ChatGenerationJob | None:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.get_generation_job(job_key)


# 指定したジョブがリプレイ可能であるかを判定する
# Determine if the specified job is replayable
def has_replayable_generation(
    job_key: str,
    *,
    service: ChatGenerationService | None = None,
) -> bool:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.has_replayable_generation(job_key)


# 指定したジョブのイベントストリームをイテレートする
# Iterate the event stream of the specified generation job
def iter_generation_events(
    job_key: str,
    *,
    after_sequence_id: int = 0,
    service: ChatGenerationService | None = None,
) -> Iterator[ChatGenerationEvent | None]:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.iter_generation_events(
        job_key,
        after_sequence_id=after_sequence_id,
    )


# 指定したパラメータで新しいチャット生成ジョブを開始する
# Start a new chat generation job with the specified parameters
def start_generation_job(
    job_key: str,
    *,
    conversation_messages: list[dict[str, Any]],
    model: str,
    persist_response: Callable[..., dict[str, Any] | None],
    locale: str = "ja",
    on_finished: Callable[[], None] | None = None,
    on_error: Callable[[], None] | None = None,
    service: ChatGenerationService | None = None,
    prior_web_search_results: list[WebSearchResult] | None = None,
    pasted_url_pages: Sequence[PastedUrlPage] = (),
    earlier_pasted_urls: Sequence[str] = (),
    personal_knowledge_search: Callable[[str], dict[str, Any]] | None = None,
    shared_prompt_search: Callable[[str], dict[str, Any]] | None = None,
    selected_reference_trace: list[SelectedReferenceLookupTrace] | None = None,
    ui_mode: GenerativeUiMode | str | None = None,
    explicit_ui_opt_out: bool = False,
    workspace_tools: ChatWorkspaceToolbox | None = None,
) -> ChatGenerationJob:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.start_generation_job(
        job_key,
        conversation_messages=conversation_messages,
        model=model,
        persist_response=persist_response,
        locale=locale,
        on_finished=on_finished,
        on_error=on_error,
        prior_web_search_results=prior_web_search_results,
        pasted_url_pages=pasted_url_pages,
        earlier_pasted_urls=earlier_pasted_urls,
        personal_knowledge_search=personal_knowledge_search,
        shared_prompt_search=shared_prompt_search,
        selected_reference_trace=selected_reference_trace,
        ui_mode=ui_mode,
        explicit_ui_opt_out=explicit_ui_opt_out,
        workspace_tools=workspace_tools,
    )
