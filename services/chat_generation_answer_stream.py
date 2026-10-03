"""回答本文をクライアントへ配信するフェーズ。

The phase that delivers the answer body to the client.

引用の解決、検索画像の露出、生成 UI パーツの更新、出力上限で切れた回答の継続生成、
未配信バッファの救済を扱う。LLM ストリームの読み取りは `_iter_llm_stream_with_retry`
（`chat_generation_llm_stream`）を呼ぶ。
Covers citation resolution, revealing search images, generated-UI part updates, continuing an
answer cut off at the output cap, and salvaging the undelivered buffer. Reading the LLM stream
goes through `_iter_llm_stream_with_retry` (`chat_generation_llm_stream`).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from services.generative_ui import normalize_response_with_artifacts
from services.message_parts_display import (
    GENERATIVE_UI_PART_TYPES,
    MAX_WEB_SEARCH_IMAGES_PER_REPLY,
)

from .chat_answer_continuation import stream_final_answer_with_recovery
from .chat_generation_job_base import ChatGenerationJobBase
from .chat_generation_turn import ChatTurnRunState
from .chat_turn_state import strip_turn_state_update_chunks
from .chat_write_claim_guard import _unconfirmed_write_claim_fallback
from .llm import LlmOutputLimitError
from .web_search import (
    WebSearchResult,
    combine_web_search_results,
    resolve_web_search_citations,
    split_web_search_citation_stream_text,
    strip_web_search_citation_html,
)
from .web_search_images import (
    build_web_search_image_parts,
    build_web_search_image_parts_at_offsets,
    choose_web_search_images,
    find_next_streaming_image_insertion,
)
from .web_search_trace import (
    answer_step,
    build_web_search_trace_markdown,
)

logger = logging.getLogger(__name__)


# ストリーミング中の応答テキストから Artifact 等の UI パーツ情報をパースして更新用ペイロードを組み立てる
# Parse UI parts like Artifacts from streaming response text and build the update payload
def _build_streaming_parts_update(raw_text: str) -> dict[str, Any] | None:
    if "chatcore-artifact" not in raw_text and "chatcore-buttons" not in raw_text:
        return None

    normalized_response = normalize_response_with_artifacts(raw_text, allow_fallback=False)
    if normalized_response.validation_errors or not normalized_response.parts:
        return None

    if not any(part.get("type") != "text" for part in normalized_response.parts):
        return None

    return {
        "response": normalized_response.text,
        "parts": normalized_response.parts,
    }


# 選択ボタンは検索画像と同じ返信に並ぶ。ボタンが確定した時点の更新を本文とボタンだけで送ると、
# ストリーム中に出した画像が完了まで消えるため、露出済みの画像を露出した位置へ戻す。
# 画像の位置は配信済みの本文（引用チップの除去後）に対するオフセットなので、生のチャンクではなく
# その本文からボタンのフェンスを除いて組み直す。生成UIを含む更新は従来どおり画像を載せない。
# Choice buttons share a reply with web-search images. Sending the update that settles the buttons
# with only the prose and the buttons would hide the images revealed so far until completion, so the
# revealed images return to their offsets. Those offsets index the streamed display text (chip markup
# already stripped), so the layout is rebuilt from that text minus the button fence, not from the raw
# chunks. An update with a generated UI stays image-free, as generated UI and images are exclusive.
def _with_revealed_stream_images(
    parts_update: dict[str, Any],
    streamed_display_text: str,
    revealed_image_parts: list[dict[str, Any]],
    revealed_image_offsets: list[int],
) -> dict[str, Any]:
    if not revealed_image_parts or any(
        part.get("type") in GENERATIVE_UI_PART_TYPES for part in parts_update["parts"]
    ):
        return parts_update
    displayed_update = _build_streaming_parts_update(streamed_display_text)
    if displayed_update is None:
        return parts_update
    inline_parts = build_web_search_image_parts_at_offsets(
        displayed_update["response"],
        revealed_image_parts,
        revealed_image_offsets,
        keep_empty_tail=True,
    )
    return {
        "response": displayed_update["response"],
        "parts": [*inline_parts, *(part for part in displayed_update["parts"] if part.get("type") != "text")],
    }


# 回答本文の配信と継続生成を担う Mixin
# Mixin that delivers the answer body and continues an interrupted answer
class ChatGenerationAnswerStreamMixin(ChatGenerationJobBase):
    # 検索結果が届いた時点で表示候補の画像を選ぶ。停止しても露出済み画像を保存できる。
    # Select images as soon as a search result arrives so a stop still keeps revealed ones.
    def _collect_web_search_image_selections(
        self,
        state: ChatTurnRunState,
        result: WebSearchResult | None,
    ) -> None:
        selected_web_search_images = state.selected_web_search_images
        if result is None or len(selected_web_search_images) >= MAX_WEB_SEARCH_IMAGES_PER_REPLY:
            return
        try:
            selections = choose_web_search_images(
                state.latest_user_message,
                result,
                answer_text=state.streamed_display_text,
            )
        except Exception:
            logger.warning(
                "Web search image selection failed during streaming; continuing without an image.",
                exc_info=True,
            )
            return
        existing_urls = {
            str(selection.get("url") or "")
            for selection in selected_web_search_images
            if isinstance(selection, dict)
        }
        for selection in selections:
            if not isinstance(selection, dict):
                continue
            image_url = str(selection.get("url") or "")
            if not image_url or image_url in existing_urls:
                continue
            selected_web_search_images.append(selection)
            existing_urls.add(image_url)
            if len(selected_web_search_images) >= MAX_WEB_SEARCH_IMAGES_PER_REPLY:
                break
        # A model-requested search can finish after prose has already streamed.
        # Reconcile selected images against that existing text immediately.
        self._publish_stream_text_with_images(state, "")

    # 表示本文を1チャンク配信し、画像挿入位置の基準となる累積テキストを進める。
    # Publish one display chunk and advance the accumulated text that anchors image offsets.
    def _publish_stream_chunk(self, state: ChatTurnRunState, text: str) -> None:
        if not text:
            return
        self._publish("chunk", {"text": text})
        state.streamed_display_text += text

    # 本文を配信しつつ、確定したオフセットで検索画像を露出する（過去本文も対象）。
    # Emit text and reveal images at stable offsets, including past text.
    def _publish_stream_text_with_images(self, state: ChatTurnRunState, text: str) -> None:
        pending_text = text
        while True:
            raw_parts_update = _build_streaming_parts_update("".join(state.chunks))
            if raw_parts_update is not None:
                if pending_text:
                    self._publish_stream_chunk(state, pending_text)
                return

            image_parts = build_web_search_image_parts(state.selected_web_search_images)
            next_image = find_next_streaming_image_insertion(
                f"{state.streamed_display_text}{pending_text}",
                image_parts,
                revealed_indices=set(state.revealed_image_indices),
                after_offset=state.revealed_image_offsets[-1] if state.revealed_image_offsets else 0,
            )
            if next_image is None:
                if pending_text:
                    self._publish_stream_chunk(state, pending_text)
                return

            insertion_offset, image_index = next_image
            current_text_length = len(state.streamed_display_text)
            relative_offset = insertion_offset - current_text_length
            if relative_offset < 0:
                relative_offset = 0
            if relative_offset > len(pending_text):
                if pending_text:
                    self._publish_stream_chunk(state, pending_text)
                return

            if relative_offset:
                self._publish_stream_chunk(state, pending_text[:relative_offset])
            state.revealed_image_indices.append(image_index)
            state.revealed_image_offsets.append(insertion_offset)
            visible_image_parts = [
                image_parts[index] for index in state.revealed_image_indices
            ]
            visible_parts = build_web_search_image_parts_at_offsets(
                state.streamed_display_text,
                visible_image_parts,
                state.revealed_image_offsets,
                keep_empty_tail=True,
            )
            self._publish(
                "response_parts_updated",
                {
                    "response": state.streamed_display_text,
                    "parts": visible_parts,
                },
            )
            pending_text = pending_text[relative_offset:]

    # ツール要求が無いと確定したモデルステップだけを、引用解決とUIパーツ更新込みで配信する。
    # Publish a model step only after confirming it requested no tools.
    def _publish_completed_answer_step(
        self,
        state: ChatTurnRunState,
        step_chunks: list[str],
    ) -> None:
        if self._workspace_tools is not None:
            fallback = _unconfirmed_write_claim_fallback(
                "".join(step_chunks), state.latest_user_message, state.tool_approval_parts
            )
            if fallback is not None:
                step_chunks = [fallback]
        chunks = state.chunks
        for raw_chunk in step_chunks:
            chunk = raw_chunk
            if not chunks:
                combined_web_search_result = combine_web_search_results(state.web_search_results)
                if state.web_search_trace_steps or combined_web_search_result is not None:
                    state.web_search_trace_steps.append(answer_step(state.web_search_results))
                trace_block = build_web_search_trace_markdown(
                    combined_web_search_result,
                    steps=state.web_search_trace_steps,
                )
                if trace_block:
                    chunk = f"{trace_block}\n\n{chunk}"

            with self._chunks_lock:
                # cancel() が既にこのステップの本文を部分回答として保存済みなら、
                # 同じ本文をここでも積むと保存内容が二重化する。ロックの下で
                # `_cancelled` を確認し、cancel() の salvage と排他にすることで防ぐ。
                # If cancel() has already persisted this step's text as the partial
                # answer, appending it here too would duplicate the saved body. Checking
                # `_cancelled` under the same lock makes this mutually exclusive with
                # cancel()'s own salvage.
                if self._cancelled:
                    return
                chunks.append(chunk)
            streaming_evidence = combine_web_search_results(
                [*state.web_search_results, *self._prior_web_search_results]
            )
            # モデルが真似て書いたチップHTMLは、検索根拠の有無にかかわらず
            # 表示前に取り除く。正規のチップはこの後の解決処理だけが描画する。
            # Chip markup echoed by the model is removed before display whether or
            # not this turn has evidence; only the resolution below renders chips.
            complete_stream_text, state.streaming_citation_buffer = (
                split_web_search_citation_stream_text(
                    f"{state.streaming_citation_buffer}{chunk}"
                )
            )
            complete_stream_text = strip_web_search_citation_html(
                complete_stream_text
            )
            if streaming_evidence is None:
                stream_text = complete_stream_text
            else:
                stream_text = resolve_web_search_citations(
                    complete_stream_text,
                    streaming_evidence,
                ).text
            if stream_text:
                self._publish_stream_text_with_images(state, stream_text)
            streaming_parts_update = _build_streaming_parts_update("".join(chunks))
            if streaming_parts_update is not None:
                if streaming_evidence is not None:
                    parts_resolution = resolve_web_search_citations(
                        streaming_parts_update["response"],
                        streaming_evidence,
                    )
                    resolved_parts_text = parts_resolution.text
                    streaming_parts_update = {
                        **streaming_parts_update,
                        "response": resolved_parts_text,
                        "parts": [
                            (
                                {**part, "text": resolved_parts_text}
                                if part.get("type") == "text"
                                else part
                            )
                            for part in streaming_parts_update["parts"]
                        ],
                    }
                stream_image_parts = build_web_search_image_parts(state.selected_web_search_images)
                streaming_parts_update = _with_revealed_stream_images(
                    streaming_parts_update,
                    state.streamed_display_text,
                    [stream_image_parts[index] for index in state.revealed_image_indices],
                    state.revealed_image_offsets,
                )
                streaming_parts_signature = json.dumps(
                    streaming_parts_update,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                if streaming_parts_signature != state.last_streaming_parts_signature:
                    state.last_streaming_parts_signature = streaming_parts_signature
                    self._publish("response_parts_updated", streaming_parts_update)

    # 継続生成の1チャンクを、繰り返し届く内部状態の封筒を除いて配信する。
    # Publish one continuation chunk, minus any repeated state envelope.
    def _publish_answer_chunk(self, state: ChatTurnRunState, chunk: str) -> None:
        visible = state.continuation_state_filter.feed(chunk)
        if visible:
            self._publish_completed_answer_step(state, [visible])

    # 継続パスの未配信バッファをジョブ側へ預ける。停止・切断でも保存経路に載る。
    # Hand the continuation pass's undelivered buffer to the job so a stop or a
    # disconnect still routes it through the persistence path.
    def _adopt_continuation_buffer(self, buffer: list[str]) -> None:
        with self._chunks_lock:
            self._pending_stream_chunks = buffer
            self._pending_stream_is_rewrite = False

    # 継続パスが全文の書き直しへ切り替わったことを停止経路へ伝える。
    # Tell the cancellation path when a continuation has switched to a full rewrite.
    def _set_continuation_buffer_mode(self, is_rewrite: bool) -> None:
        with self._chunks_lock:
            self._pending_stream_is_rewrite = is_rewrite

    # 出力上限で切れた回答の続きだけを取り直すフェーズ。
    # The phase that fetches only the remainder of an answer cut off at the output cap.
    def _continue_interrupted_answer(
        self,
        state: ChatTurnRunState,
        answer_messages: list[dict[str, Any]],
        published_text: str,
        *,
        memo_tail_start: int | None = None,
    ) -> BaseException | None:
        """Continue an answer the provider cut off at its output cap.

        回答を書いたモデル判断だけが継続の対象で、別フェーズは作らない。すでに配信した
        本文を assistant 履歴として渡し、続きだけを同じループの延長として受け取る。
        Only the decision that wrote the answer is continued; no separate phase is created.
        The published text is replayed as assistant history so the provider returns just
        the remainder of the same answer.
        """
        telemetry = state.telemetry
        interruption = LlmOutputLimitError(
            "The answer stream stopped at the model output limit.",
            reason="max_output_tokens",
        )

        def publish_continuation_chunk(chunk: str) -> None:
            if memo_tail_start is None:
                self._publish_answer_chunk(state, chunk)
                return
            visible = state.continuation_state_filter.feed(chunk)
            if visible:
                with self._chunks_lock:
                    if not self._cancelled:
                        state.chunks.append(visible)

        try:
            result = stream_final_answer_with_recovery(
                answer_messages,
                model=self._model,
                iter_stream=lambda messages, phase: self._iter_llm_stream_with_retry(
                    messages,
                    tools=None,
                    generation_phase=phase,
                ),
                publish_chunk=publish_continuation_chunk,
                publish_event=self._publish,
                should_stop=self._should_stop,
                adopt_buffer=self._adopt_continuation_buffer,
                adopt_buffer_mode=self._set_continuation_buffer_mode,
                answer_phase="agent",
                continuation_phase="continuation_deep",
                published_answer_text=published_text,
                published_answer_error=interruption,
            )
        finally:
            # 通常完了・入力超過・キャンセルのどの経路でも、次の保存処理が古い共有
            # バッファや書き直しモードを誤って拾わないようにする。
            # Clear shared state on every exit so later persistence cannot adopt a stale
            # continuation buffer or rewrite mode.
            with self._chunks_lock:
                self._pending_stream_chunks = []
                self._pending_stream_is_rewrite = False
        trailing = state.continuation_state_filter.flush()
        if trailing:
            if memo_tail_start is None:
                self._publish_completed_answer_step(state, [trailing])
            else:
                with self._chunks_lock:
                    if not self._cancelled:
                        state.chunks.append(trailing)
        if memo_tail_start is not None:
            # The first pass may end in the middle of a memo status sentence. Keep only
            # that unfinished tail and its continuation off the wire until it is complete.
            with self._chunks_lock:
                if not self._cancelled:
                    completed_tail = "".join(state.chunks[memo_tail_start:])
                    del state.chunks[memo_tail_start:]
                    if completed_tail:
                        self._publish_completed_answer_step(state, [completed_tail])
        state.continuation_count = result.continuation_count
        telemetry.continuation_count = result.continuation_count
        for reason in result.reasons:
            telemetry.record_continuation_reason(reason)
        telemetry.continuation_stalled = result.stalled
        telemetry.continuation_restart_trimmed = result.restart_trimmed
        telemetry.first_pass_finish_reason = interruption.reason
        return result.error

    # 引用チップ判定のために保留していた末尾を、ループ終了後に配信するフェーズ。
    # The phase that flushes the tail held back for citation-chip detection once the loop ends.
    def _flush_streaming_citation_buffer(self, state: ChatTurnRunState) -> None:
        if not state.streaming_citation_buffer:
            return
        streaming_evidence = combine_web_search_results(
            [*state.web_search_results, *self._prior_web_search_results]
        )
        buffered_text = strip_web_search_citation_html(
            state.streaming_citation_buffer
        )
        if streaming_evidence is not None:
            buffered_text = resolve_web_search_citations(
                buffered_text,
                streaming_evidence,
            ).text
        if buffered_text:
            self._publish_stream_text_with_images(state, buffered_text)

    # 未配信のまま終わりかけた本文を、成功時と同じ配信経路へ載せ直すフェーズ。
    # The phase that pushes body text left undelivered through the normal publish path.
    def _salvage_pending_answer_text(self, state: ChatTurnRunState) -> bool:
        """Publish buffered answer text so a failed turn does not throw it away.

        回答ステップの本文は「ツール呼び出しが無い」と確定するまで配信されない。つまり
        本文をストリームしている最中に失敗すると、モデルが書き終えた分がバッファにしか
        存在しない。停止時はこれを保存しているのに失敗時だけ捨てていたため、エラー文
        だけが残っていた。成功時と同じ `_publish_completed_answer_step` へ載せることで、
        トレース前置と引用解決も同じ形で適用される。
        The body of an answer step is not published until the step is known to request no
        tools, so a failure mid-body leaves everything the model wrote in the buffer only.
        Cancellation persisted that text while failures dropped it, which is why an error
        message was all that remained. Routing it through the same
        `_publish_completed_answer_step` keeps the trace prefix and citation resolution identical
        to the success path.
        """
        pending_text = self._take_pending_answer_text()
        if not pending_text:
            return False
        visible_chunks = strip_turn_state_update_chunks([pending_text])
        if not visible_chunks:
            return False
        self._publish_completed_answer_step(state, visible_chunks)
        state.telemetry.salvaged_partial_answers += 1
        return True
