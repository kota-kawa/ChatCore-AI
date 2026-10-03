"""生成結果の仕上げ（正規化・引用解決・保存・終端イベント）と、失敗の通知フェーズ。

The phase that finalizes a generation (normalization, citations, persistence, terminal event)
and reports failures.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from services.error_messages import ERROR_CHAT_EMPTY_RESPONSE
from services.generative_ui import (
    NormalizedGenerativeResponse,
    artifact_status_part,
    normalize_response_with_artifact_retry,
    normalize_response_with_artifacts,
)
from services.generative_ui_repair import with_answer_output_budget
from services.generative_ui_status import ARTIFACT_STATUS_PART_TYPE
from services.i18n import translate_text
from services.message_parts_display import (
    GENERATIVE_UI_PART_TYPES,
    WEB_SEARCH_IMAGE_PART_TYPE,
    normalize_message_parts_for_display,
)
from services.tool_approval_parts import TOOL_APPROVAL_PART_TYPE

from .chat_answer_continuation import FinalAnswerContinuationStalledError
from .chat_generation_job_base import (
    ChatGenerationJobBase,
    _has_executed_approval,
    _latest_user_message_text,
    _with_tool_approval_parts,
)
from .chat_generation_turn import ChatTurnRunState
from .chat_write_claim_guard import _unconfirmed_write_claim_fallback
from .llm import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmInputLimitError,
    LlmOutputLimitError,
    LlmRateLimitError,
    LlmRetryableProviderError,
    LlmServiceError,
    get_llm_response,
    is_retryable_llm_error,
)
from .web_search import (
    WebSearchCitation,
    combine_web_search_results,
    resolve_web_search_citations,
    serialize_web_search_result_for_storage,
    strip_web_search_citation_html,
    with_web_search_citations,
)
from .web_search_images import append_web_search_image_parts

logger = logging.getLogger(__name__)


# 完了したターンにユーザーが読める回答があるかを判定する。検索画像だけ・トレースだけは回答ではない。
# Decide whether a finished turn carries an answer the user can read; images or a trace alone are not one.
def _has_user_facing_answer(
    *,
    model_text: str,
    response_text: str,
    message_parts: list[dict[str, Any]] | None,
) -> bool:
    """Return whether a finished turn carries an answer the user can read.

    モデルが本文を書いたか（正規化前の生テキスト）、生成UIがあるか、承認カードがあるかで判定する。
    正規化で本文が消えた場合は、テキストと検索画像以外のパーツがあるときだけ回答扱いにする。
    Answered means the model wrote body text (raw, before normalization), produced a generated
    UI, or left an approval card. If normalization emptied the body, only parts other than text
    and web-search images keep the turn answered.
    """
    parts = [part for part in (message_parts or []) if isinstance(part, dict)]
    # 承認カードは利用者が決める対象そのものなので、本文が無くても回答として残す。
    # An approval card is itself what the user must decide on, so it stands as an answer even
    # without body text.
    if any(part.get("type") == TOOL_APPROVAL_PART_TYPE for part in parts):
        return True
    has_generative_ui = any(part.get("type") in GENERATIVE_UI_PART_TYPES for part in parts)
    if not model_text.strip() and not has_generative_ui:
        return False
    if response_text.strip():
        return True
    return any(
        part.get("type") not in (WEB_SEARCH_IMAGE_PART_TYPE, ARTIFACT_STATUS_PART_TYPE, "text")
        for part in parts
    )


# 生成結果の仕上げと失敗の通知を担う Mixin
# Mixin that finalizes the generation result and reports failures
class ChatGenerationFinalizationMixin(ChatGenerationJobBase):
    # 生成失敗をユーザー向けイベントと運用ログの両方へ落とすフェーズ。
    # The phase that turns a generation failure into both a user event and an operations log.
    def _report_generation_failure(
        self,
        exc: Exception,
        state: ChatTurnRunState,
    ) -> None:
        if self._cancelled:
            return
        # 本文を1文字も出していない場合だけ、呼び出し元のエラーコールバックを起動する。
        # Only a turn that emitted no body text at all invokes the caller's error callback.
        invoke_error_callback = not state.chunks
        if isinstance(exc, LlmConfigurationError):
            logger.exception(
                "Chat generation stopped due to an LLM configuration error.",
                extra=self._telemetry.as_log_extra(),
            )
            error_message = "LLM設定エラーが発生しました。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": False},
                invoke_error_callback=invoke_error_callback,
            )
            return
        if isinstance(exc, LlmAuthenticationError):
            logger.exception(
                "Chat generation stopped due to an LLM provider authentication error.",
                extra=self._telemetry.as_log_extra(),
            )
            error_message = "LLMプロバイダ認証エラーが発生しました。設定を確認してください。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": False},
                invoke_error_callback=invoke_error_callback,
            )
            return
        if isinstance(exc, LlmRateLimitError):
            logger.warning(
                "Chat generation hit an LLM provider rate limit (retry_after_seconds=%s): %s",
                exc.retry_after_seconds,
                exc,
                exc_info=exc,
                extra=self._telemetry.as_log_extra(),
            )
            error_message = "AI提供元が混み合っています。時間をおいて再試行してください。"
            payload: dict[str, Any] = {
                "message": error_message,
                "retryable": True,
            }
            if exc.retry_after_seconds is not None:
                payload["retry_after_seconds"] = exc.retry_after_seconds
            self._handle_error(
                error_message,
                payload,
                invoke_error_callback=invoke_error_callback,
            )
            return
        if isinstance(exc, LlmInputLimitError):
            logger.warning(
                "Chat generation stopped because the request exceeded the model context window.",
                exc_info=exc,
                extra=self._telemetry.as_log_extra(),
            )
            error_message = (
                "参照した情報が多すぎて、モデルが一度に扱える上限を超えました。"
                "質問を分けるか、参照を減らして再試行してください。"
            )
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": True},
                invoke_error_callback=invoke_error_callback,
            )
            return
        if isinstance(exc, LlmServiceError):
            retryable = is_retryable_llm_error(exc)
            if retryable:
                error_message = "一時的な内部エラーが発生しました。時間をおいて再試行してください。"
            else:
                error_message = "内部エラーが発生しました。"
            logger.exception(
                "Chat generation stopped due to an LLM service error (retryable=%s).",
                retryable,
                extra={**self._telemetry.as_log_extra(), "llm_error_type": exc.__class__.__name__},
            )
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": retryable},
                invoke_error_callback=invoke_error_callback,
            )
            return
        logger.exception(
            "Unexpected error while generating chat response.",
            extra=self._telemetry.as_log_extra(),
        )
        error_message = "内部エラーが発生しました。"
        self._handle_error(
            error_message,
            {"message": error_message, "retryable": False},
            invoke_error_callback=invoke_error_callback,
        )

    # 生成本文を正規化するフェーズ。途中終了したターンは生成UIの再試行を行わない。
    # The phase that normalizes the generated body; a truncated turn skips the generated-UI retry.
    def _normalize_final_answer(
        self,
        state: ChatTurnRunState,
        bot_reply: str,
        latest_user_message: str,
    ) -> NormalizedGenerativeResponse:
        if state.final_answer_incomplete is not None:
            return normalize_response_with_artifacts(
                bot_reply,
                recover_truncated=True,
                ui_mode=self._ui_mode,
                explicit_ui_opt_out=self._explicit_ui_opt_out,
            )
        return normalize_response_with_artifact_retry(
            bot_reply,
            conversation_messages=state.answer_context_messages or state.current_messages,
            model=self._model,
            generate_response=with_answer_output_budget(get_llm_response),
            user_request=latest_user_message,
            ui_mode=self._ui_mode,
            explicit_ui_opt_out=self._explicit_ui_opt_out,
        )

    # 引用markerを検証済みソースへのリンクへ解決するフェーズ。
    # The phase that resolves citation markers into links to verified sources.
    def _resolve_final_citations(
        self,
        state: ChatTurnRunState,
        bot_reply: str,
        message_parts: list[dict[str, Any]] | None,
    ) -> tuple[str, list[dict[str, Any]] | None, tuple[WebSearchCitation, ...]]:
        # 現在ターンと過去ターンの検索根拠を照合し、モデルの引用markerを
        # 検証済みソースへのMarkdownリンクへ変換する。UIパーツがある場合も
        # 表示本文と保存本文が一致するよう、text partを同時に更新する。
        # Resolve model citation markers against current and prior evidence, then
        # keep the visible text part aligned with the persisted response.
        # 保存本文からもチップHTMLを取り除いてから、引用markerを解決する。
        # 順序を逆にすると、描画したばかりの正規チップまで消えてしまう。
        # Strip chip markup from the persisted body before resolving citation markers.
        # The reverse order would delete the chips this step just rendered.
        bot_reply = strip_web_search_citation_html(bot_reply)
        citation_evidence = combine_web_search_results(
            [*state.web_search_results, *self._prior_web_search_results]
        )
        resolved_citations: tuple[WebSearchCitation, ...] = ()
        if citation_evidence is None:
            return bot_reply, message_parts, resolved_citations

        citation_resolution = resolve_web_search_citations(
            bot_reply,
            citation_evidence,
        )
        if citation_resolution.invalid_markers:
            logger.warning(
                "Removed invalid web search citation markers from generated response.",
                extra={
                    "invalid_marker_count": len(citation_resolution.invalid_markers)
                },
            )
        bot_reply = citation_resolution.text
        resolved_citations = citation_resolution.citations
        if message_parts:
            message_parts = [
                (
                    {**part, "text": bot_reply}
                    if part.get("type") == "text"
                    else part
                )
                for part in message_parts
            ]
        return bot_reply, message_parts, resolved_citations

    # 回答が無いターンを成功として保存せず、エラーとして通知するフェーズ。
    # The phase that reports an answerless turn as an error instead of persisting it.
    def _report_empty_response(self, state: ChatTurnRunState, model_text: str) -> None:
        logger.warning(
            "Chat generation produced an empty response.",
            extra={
                **self._telemetry.as_log_extra(),
                "has_model_text": bool(model_text.strip()),
                "selected_image_count": len(state.selected_web_search_images),
            },
        )
        error_message = ERROR_CHAT_EMPTY_RESPONSE
        self._handle_error(
            error_message,
            {"message": error_message, "retryable": True},
            invoke_error_callback=True,
        )

    # 途中終了の理由をユーザー向け文言へ変換する。
    # Translate why the answer ended early into a user-facing sentence.
    def _partial_answer_message(self, error: BaseException) -> str:
        if isinstance(error, FinalAnswerContinuationStalledError):
            message = "回答の続きを生成できず、途中までの回答を保存しました。"
        elif isinstance(error, LlmOutputLimitError):
            message = "回答が非常に長く、継続生成の上限に達しました。途中までの回答を保存しました。"
        elif isinstance(error, LlmInputLimitError):
            message = (
                "参照した情報が多すぎて、モデルが一度に扱える上限を超えました。"
                "途中までの回答を保存しました。"
            )
        elif isinstance(error, LlmRateLimitError):
            message = "AI提供元が混み合っているため中断しました。途中までの回答を保存しました。"
        elif isinstance(error, LlmRetryableProviderError):
            message = "AI提供元との接続が途中で終了しました。途中までの回答を保存しました。"
        elif isinstance(error, LlmServiceError):
            message = "生成が途中で終了しました。途中までの回答を保存しました。"
        else:
            message = "AI提供元との接続が途中で終了しました。途中までの回答を保存しました。"
        return translate_text(message, self._locale)

    # 応答を履歴へ保存し、done / incomplete の終端イベントを発行するフェーズ。
    # The phase that persists the reply and publishes the terminal done / incomplete event.
    def _persist_and_publish_result(
        self,
        state: ChatTurnRunState,
        bot_reply: str,
        message_parts: list[dict[str, Any]] | None,
        resolved_citations: tuple[WebSearchCitation, ...],
    ) -> None:
        # このターンで取得した検索結果を直列化し、後続ターンで参照できるよう永続化する
        # Serialize this turn's search results so later turns can reference them.
        serialized_web_search = [
            serialize_web_search_result_for_storage(
                with_web_search_citations(result, resolved_citations)
            )
            for result in state.web_search_results
            if result.has_sources
        ]

        try:
            persist_metadata = self._persist_once(
                bot_reply,
                message_parts,
                web_search_context=serialized_web_search or None,
                approval_cards=state.tool_approval_parts,
            )
        except Exception:
            logger.exception("Failed to persist background chat response.")
            error_message = "応答は生成されましたが、履歴保存に失敗しました。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": True},
                invoke_error_callback=not bot_reply,
            )
            return

        done_payload: dict[str, Any] = {"response": bot_reply}
        if message_parts:
            done_payload["parts"] = message_parts
        if self._artifact_status_payload:
            done_payload["artifact_status"] = self._artifact_status_payload
        if isinstance(persist_metadata, dict):
            done_payload.update(persist_metadata)
        self._telemetry.final_answer_output_chars = len(bot_reply)
        self._telemetry.evidence_budget_consumed = state.evidence_context_budget.consumed
        if state.final_answer_incomplete is not None:
            incomplete_payload = {
                **done_payload,
                "message": self._partial_answer_message(state.final_answer_incomplete),
                "partial": True,
                "retryable": (
                    isinstance(state.final_answer_incomplete, LlmOutputLimitError)
                    or is_retryable_llm_error(state.final_answer_incomplete)
                ),
                "continuations": state.continuation_count,
            }
            logger.info(
                "Chat generation ended with a persisted partial answer.",
                extra={
                    "terminal_event": "incomplete",
                    "output_chars": len(bot_reply),
                    "duration_seconds": round(time.monotonic() - self.started_at, 3),
                    **self._telemetry.as_log_extra(),
                },
            )
            self._publish("incomplete", incomplete_payload, done=True)
            return
        logger.info(
            "Chat generation completed.",
            extra={
                "terminal_event": "done",
                "output_chars": len(bot_reply),
                "duration_seconds": round(time.monotonic() - self.started_at, 3),
                **self._telemetry.as_log_extra(),
            },
        )
        self._publish("done", done_payload, done=True)

    # 生成UIの判定・検証・修復の結果をテレメトリと配信用の状態へ確定するフェーズ。
    # The phase that settles the generated-UI decision, validation and repair outcome into
    # telemetry and the status delivered to the client.
    def _record_generated_ui_outcome(
        self,
        normalized_response: NormalizedGenerativeResponse,
    ) -> None:
        self._telemetry.ui_mode = str(self._ui_mode or "")
        self._telemetry.ui_mode_decision_status = (
            "disabled" if self._explicit_ui_opt_out else "decided" if self._ui_mode else "failed"
        )
        self._telemetry.explicit_ui_opt_out = self._explicit_ui_opt_out
        self._telemetry.record_generated_ui_outcome(
            status=normalized_response.artifact_status,
            reason_codes=normalized_response.artifact_reason_codes,
            repair_attempted=normalized_response.repair_attempted,
        )
        self._artifact_status_payload = normalized_response.status_payload()
        if normalized_response.validation_errors:
            logger.warning(
                "One or more generated UI artifacts failed validation and were omitted.",
                extra={
                    "validation_errors": normalized_response.validation_errors,
                    "artifact_status": normalized_response.artifact_status,
                    "artifact_reason_codes": normalized_response.artifact_reason_codes,
                },
            )

    # 生成結果を正規化・引用解決・画像配置してから保存と終端通知へ渡すフェーズ。
    # The phase that normalizes, resolves citations and places images before persisting.
    def _finalize_generation(self, state: ChatTurnRunState) -> None:
        # モデルが本文を書いたかは、正規化や画像配置の前に生の chunks で確定する。
        # 本文ゼロのターンにトレースだけを前置して完了扱いにはしない。
        # Whether the model wrote any body text is settled from the raw chunks before
        # normalization and image placement. A turn with no body never gets a trace-only body.
        model_text = "".join(state.chunks)
        latest_user_message = _latest_user_message_text(self._conversation_messages)
        normalized_response = self._normalize_final_answer(
            state,
            model_text,
            latest_user_message,
        )
        if self._workspace_tools is not None:
            fallback = _unconfirmed_write_claim_fallback(
                normalized_response.text, latest_user_message, state.tool_approval_parts
            )
            if fallback is not None:
                normalized_response = normalize_response_with_artifacts(
                    fallback,
                    ui_mode=self._ui_mode,
                    explicit_ui_opt_out=self._explicit_ui_opt_out,
                )
        self._record_generated_ui_outcome(normalized_response)
        bot_reply = normalized_response.text
        message_parts = normalized_response.parts
        status_part = artifact_status_part(self._artifact_status_payload)
        if status_part:
            message_parts = [*(message_parts or [{"type": "text", "text": bot_reply}]), status_part]

        bot_reply, message_parts, resolved_citations = self._resolve_final_citations(
            state,
            bot_reply,
            message_parts,
        )
        # 画像は検索結果を取得した時点で選定済み。引用解決後は、選定LLMが返した
        # 配置計画を本文へ反映し、ストリーム中に表示した順序と保存内容を一致させる。
        # Image selection already happened when each search result arrived. After
        # citation resolution, realize the placement plan returned by the selector
        # so persisted history matches what the stream revealed.
        if state.selected_web_search_images:
            message_parts = append_web_search_image_parts(
                message_parts,
                state.selected_web_search_images,
                fallback_text=bot_reply,
            )

        # トレースを独立パーツへ分け、本文内の画像位置を維持したまま保存・配信する。
        # Finalize the trace split while preserving inline image positions.
        if message_parts:
            message_parts = normalize_message_parts_for_display(message_parts) or None
        # 承認カードは本文と画像の後ろ、回答の最後に置く。
        # Approval cards close the reply, after the body and the images.
        message_parts = _with_tool_approval_parts(message_parts, bot_reply, state.tool_approval_parts)

        self.response = bot_reply

        # 本文も生成UIも無ければ「回答なし」であり、成功として保存してはいけない。
        # 検索画像やトレースだけでは回答にならない。空の応答を保存すると空の吹き出し
        # （画像だけ・ステップだけの吹き出し）が残り、ユーザー発話だけが積み上がる。
        # No body and no generated UI means there is no answer at all, so it must not be
        # persisted as a success: search images or a trace alone are not an answer, and an
        # empty reply leaves a blank (image-only / steps-only) bubble behind while
        # unanswered user messages pile up.
        if not _has_user_facing_answer(
            model_text=model_text,
            response_text=bot_reply,
            message_parts=message_parts,
        ):
            self._report_empty_response(state, model_text)
            return

        self._persist_and_publish_result(
            state,
            bot_reply,
            message_parts,
            resolved_citations,
        )

    # 失敗したターンでも本文が残っていれば、途中までの回答として保存して締めるフェーズ。
    # The phase that closes a failed turn as a saved partial answer when body text survived.
    def _finalize_failed_turn(self, exc: Exception, state: ChatTurnRunState) -> bool:
        """Persist what the turn produced instead of replacing it with an error.

        LLM が本文を書けていた以上、それはユーザーにとっての回答である。失敗したのが
        仕上げ段階でも配信途中でも、保存して `incomplete` で締めれば、履歴にも残り
        続きの生成もできる。ここで False を返したときだけエラー表示へ落ちる。
        Once the model has written body text, that text is the user's answer. Whether the
        failure hit finalization or mid-delivery, persisting it and closing with `incomplete`
        keeps it in history and leaves the continuation affordance available. Only a False
        return falls through to the error path.
        """
        if self._cancelled or self.is_done:
            return False
        try:
            self._salvage_pending_answer_text(state)
            # 失敗したターンでも、未実行の承認待ちは取り消す。自動承認で実行済みの書き込みは
            # 取り消せないので、本文が無くてもそのカードを保存する。
            # A failed turn still cancels its pending approvals. A write already run through auto
            # approval cannot be undone, so its card is saved even without body text.
            self._settle_approvals_after_interruption()
            if not "".join(state.chunks).strip() and not _has_executed_approval(state.tool_approval_parts):
                return False
            self._flush_streaming_citation_buffer(state)
            # 途中終了の印を立てると、仕上げは生成UIの再試行（追加のLLM呼び出し）を
            # 行わず、打ち切られた本文の復旧だけを行う。
            # Marking the turn incomplete makes finalization skip the generated-UI retry (an
            # extra LLM call) and only recover the truncated body.
            state.final_answer_incomplete = exc
            self._finalize_generation(state)
        except Exception:
            logger.exception(
                "Failed to save the partial answer of a failed chat generation turn.",
                extra=self._telemetry.as_log_extra(),
            )
            return False
        return self.is_done
