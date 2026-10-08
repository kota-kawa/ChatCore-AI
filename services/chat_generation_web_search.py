"""Web 検索ツールの呼び出し1件を実行し、根拠・トレース・ツール結果へ反映するフェーズ。

The phase that runs one web-search tool call and folds it into evidence, trace and tool result.

検索結果が届いた時点の画像選定は `_collect_web_search_image_selections`
（`chat_generation_answer_stream`）を呼ぶ。
Image selection when a result arrives goes through `_collect_web_search_image_selections`
(`chat_generation_answer_stream`).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .chat_generation_job_base import ChatGenerationJobBase
from .chat_generation_telemetry import ChatGenerationTelemetry
from .chat_generation_turn import ChatTurnRunState
from .chat_tool_calls import (
    _tool_argument_text,
    _tool_result_message,
)
from .generative_ui_images import GENERATED_UI_IMAGES_TOOL_KEY, build_generated_ui_image_catalog
from .web_search import (
    WEB_SEARCH_ERROR_QUOTA_EXCEEDED,
    WEB_SEARCH_ERROR_REQUEST_FAILED,
    WEB_SEARCH_MAX_CONTEXT_CHARS,
    WEB_SEARCH_TOOL_CONTEXT_MAX_CHARS,
    WebEvidenceContextBudget,
    WebSearchQuotaExceededError,
    WebSearchResult,
    normalize_search_language,
    normalize_web_search_freshness,
    search_brave_llm_context,
)
from .web_search_trace import (
    page_reading_steps,
    review_step,
    search_failed_step,
    search_step,
)

logger = logging.getLogger(__name__)


# 検索クエリ・日付フィルタ・検索言語を正規化したキーを生成する
# Generate a normalized key from the query, freshness filter, and search language
def _normalized_search_key(
    query: Any,
    freshness: Any = "",
    search_language: Any = "",
) -> tuple[str, str, str]:
    normalized_query = " ".join(str(query or "").split())
    normalized_freshness = str(freshness or "").strip()
    normalized_language = str(search_language or "").strip().casefold()
    return (normalized_query.casefold(), normalized_freshness, normalized_language)


# ツールへ返却するWeb検索結果ペイロードを整形する
# Format the Web search result payload returned to the tool
def _web_search_result_tool_payload(
    result: WebSearchResult,
    *,
    cached: bool = False,
    max_chars: int = WEB_SEARCH_MAX_CONTEXT_CHARS,
) -> dict[str, Any]:
    max_chars = max(1, min(int(max_chars), WEB_SEARCH_MAX_CONTEXT_CHARS))
    sources: list[dict[str, Any]] = []
    for source in result.sources:
        item: dict[str, Any] = {
            "evidence_id": source.evidence_id,
            "url": source.url[:320],
            "title": source.title[:160],
            "hostname": source.hostname[:120],
            "age": source.age[:80],
            "snippets": [],
        }
        if source.link_depth:
            item["link_depth"] = source.link_depth
        if source.linked_from_url:
            item["linked_from_url"] = source.linked_from_url[:160]
        sources.append(item)

    payload: dict[str, Any] = {
        "status": "completed",
        "cached": cached,
        "query": result.query[:240],
        "searched_at": result.searched_at[:80],
        "source_count": len(result.sources),
        "sources": sources,
    }
    detailed_count = sum(
        1 for source in result.sources if source.snippets or source.page_text
    )
    base_length = len(json.dumps(payload, ensure_ascii=False))
    per_source_budget = max(
        0,
        (max_chars - base_length) // max(1, detailed_count) - 32,
    )
    for item, source in zip(sources, result.sources, strict=True):
        remaining = per_source_budget
        if source.snippets and remaining > 0:
            snippet = source.snippets[0][: min(400, remaining)]
            item["snippets"] = [snippet]
            remaining -= len(snippet)
        if source.page_text and remaining > 0:
            item["page_text"] = source.page_text[:remaining]

    # JSON escaping adds a small amount of overhead. Trim details, never source IDs,
    # until the serialized tool result is within the same context budget.
    while len(json.dumps(payload, ensure_ascii=False)) > max_chars:
        overflow = len(json.dumps(payload, ensure_ascii=False)) - max_chars
        changed = False
        for item in reversed(sources):
            page_text = item.get("page_text")
            if isinstance(page_text, str) and page_text:
                item["page_text"] = page_text[: max(0, len(page_text) - overflow - 8)]
                changed = True
                break
            snippets = item.get("snippets")
            if isinstance(snippets, list) and snippets:
                item["snippets"] = []
                changed = True
                break
        if not changed:
            break
    # Adversarial metadata can expand substantially when JSON-escaped. Remove optional
    # fields in a stable order while preserving every server-issued evidence ID.
    optional_fields = (
        "linked_from_url",
        "age",
        "url",
        "hostname",
        "title",
        "link_depth",
        "snippets",
    )
    for field in optional_fields:
        if len(json.dumps(payload, ensure_ascii=False)) <= max_chars:
            break
        for item in reversed(sources):
            item.pop(field, None)
            if len(json.dumps(payload, ensure_ascii=False)) <= max_chars:
                break
    if len(json.dumps(payload, ensure_ascii=False)) > max_chars:
        payload["query"] = ""
        payload["searched_at"] = ""

    # 予算を使い切ると本文もスニペットも残らない。それを "completed" のまま返すと、
    # モデルは「検索は成功したが何も書いていない」根拠を受け取り、出典IDだけを引用しかねない。
    # 状態を明示し、追加検索ではなく既存の根拠で答えるよう伝える。
    # An exhausted budget leaves neither page text nor snippets. Returning that as
    # "completed" hands the model evidence that succeeded yet says nothing, and invites it to
    # cite bare source IDs. Say so explicitly and steer it back to the evidence it already has.
    if detailed_count and not any(
        item.get("page_text") or item.get("snippets") for item in sources
    ):
        payload["status"] = "evidence_truncated"
        payload["message"] = (
            "This answer's evidence budget is exhausted, so the source text was omitted. "
            "Answer from the evidence already gathered and do not request another search."
        )
        # The status explanation is added after optional metadata has been trimmed. Keep the
        # explanation within the requested budget whenever the required evidence IDs leave room;
        # for an impossibly tiny budget, preserving IDs and the explicit status is safer than
        # silently returning a misleading successful result.
        while len(json.dumps(payload, ensure_ascii=False)) > max_chars:
            message = payload.get("message")
            if not isinstance(message, str) or not message:
                break
            overflow = len(json.dumps(payload, ensure_ascii=False)) - max_chars
            if len(message) <= overflow + 8:
                break
            payload["message"] = f"{message[: len(message) - overflow - 8].rstrip()}..."
    return payload


def _budgeted_web_search_result_tool_payload(
    result: WebSearchResult,
    budget: WebEvidenceContextBudget,
    *,
    cached: bool = False,
    telemetry: ChatGenerationTelemetry | None = None,
) -> dict[str, Any]:
    limit = budget.message_limit(WEB_SEARCH_TOOL_CONTEXT_MAX_CHARS)
    payload = _web_search_result_tool_payload(
        result,
        cached=cached,
        max_chars=limit,
    )
    budget.consume(len(json.dumps(payload, ensure_ascii=False)))
    if telemetry is not None:
        truncated = payload.get("status") == "evidence_truncated"
        telemetry.record_evidence_payload(
            empty=truncated and not payload.get("query"),
            truncated=truncated,
        )
    return payload


# Web 検索ツールの実行を担う Mixin
# Mixin that runs the web-search tool
class ChatGenerationWebSearchMixin(ChatGenerationJobBase):
    # Web検索ツールの要求1件を、引数正規化からキャッシュ判定・実行まで進めるフェーズ。
    # The phase that carries one web-search tool call from argument normalization
    # through the cache check to execution.
    def _run_web_search_tool_call(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
    ) -> None:
        budget = state.budget
        args_raw = tool_call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(args_raw)
        except Exception:
            # 日本語: モデルが渡したツール引数が JSON として壊れていた場合は空引数として扱います。
            # English: Treat tool arguments the model produced as empty when they are not valid JSON.
            logger.debug("Discarded malformed tool-call arguments from the model.", exc_info=True)
            args = {}
        if not isinstance(args, dict):
            args = {}

        if budget.tool_calls_exhausted:
            state.current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "step_limit_reached",
                        "message": "The web search limit has been reached.",
                    },
                )
            )
            return

        search_step_index = budget.start_tool_call()
        state.telemetry.tool_calls = budget.tool_calls

        # プロバイダ側のスキーマ検証には頼らない。モデルが返した引数はここで
        # 正規化し、想定外の値は既定へ丸めてターンを進める。
        # Never rely on provider-side schema validation: normalize the model's
        # arguments here and round unexpected values to a default so the turn
        # keeps moving.
        query = _tool_argument_text(args.get("query"))
        freshness = normalize_web_search_freshness(args.get("freshness"))
        search_language = normalize_search_language(args.get("search_language"))
        if not query:
            state.turn_state.record_search(
                tool_name="web_search",
                status="invalid_arguments",
            )
            state.current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "invalid_arguments",
                        "message": "Search query is empty.",
                    },
                )
            )
            return
        query_text = query
        freshness_text = freshness
        search_key = _normalized_search_key(
            query_text,
            freshness_text,
            search_language,
        )
        cached_result = state.web_search_results_by_key.get(search_key)

        self._publish(
            "web_search_started",
            {
                "query": query_text,
                "reason": "Model-requested search",
                "step": search_step_index,
                "max_steps": budget.max_steps,
                "cached": cached_result is not None,
            },
        )
        if cached_result is not None:
            self._reuse_cached_web_search(
                state,
                tool_call,
                cached_result,
                query_text=query_text,
                step=search_step_index,
            )
            return

        try:
            self._execute_web_search(
                state,
                tool_call,
                query_text=query_text,
                freshness_text=freshness_text,
                search_language=search_language,
                search_key=search_key,
                step=search_step_index,
            )
        except WebSearchQuotaExceededError as exc:
            self._report_web_search_quota_exceeded(
                state,
                tool_call,
                exc,
                query_text=query_text,
                step=search_step_index,
            )
        except Exception:
            self._report_web_search_failure(
                state,
                tool_call,
                query_text=query_text,
                step=search_step_index,
            )

    # 同一条件の検索結果を再利用するフェーズ。プロバイダへは問い合わせない。
    # The phase that reuses an identical earlier search instead of calling the provider.
    def _reuse_cached_web_search(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        cached_result: WebSearchResult,
        *,
        query_text: str,
        step: int,
    ) -> None:
        cached_refs = state.evidence_store.add_web_result(cached_result)
        state.turn_state.record_search(
            tool_name="web_search",
            query=query_text,
            evidence_refs=cached_refs,
            searched_at=cached_result.searched_at,
            freshness=cached_result.freshness,
            status="cached",
        )
        state.web_search_trace_steps.extend(
            [
                search_step(cached_result, cached=True),
                review_step(cached_result, reused=True),
            ]
        )
        self._publish(
            "web_search_completed",
            {
                "query": cached_result.query,
                "source_count": len(cached_result.sources),
                "step": step,
                "max_steps": state.budget.max_steps,
                "cached": True,
            },
        )
        self._collect_web_search_image_selections(state, cached_result)
        state.telemetry.cached_web_search_count += 1
        tool_payload = _budgeted_web_search_result_tool_payload(
            cached_result,
            state.evidence_context_budget,
            cached=True,
            telemetry=state.telemetry,
        )
        tool_payload = self._with_generated_ui_images(state, tool_payload)
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                tool_payload,
            )
        )

    # 新規のWeb検索を実行し、根拠・トレース・ツール結果へ反映するフェーズ。
    # The phase that runs a fresh web search and folds it into evidence, trace and tool result.
    def _execute_web_search(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        *,
        query_text: str,
        freshness_text: str,
        search_language: str,
        search_key: tuple[str, str, str],
        step: int,
    ) -> None:
        result = search_brave_llm_context(
            query_text,
            freshness=freshness_text,
            page_fetch_budget=state.page_fetch_budget,
            language_hint=state.latest_user_message,
            search_language=search_language,
        )
        state.web_search_results_by_key[search_key] = result
        state.web_search_trace_steps.extend(
            [
                search_step(result, additional=bool(state.web_search_results)),
                *page_reading_steps(result),
                review_step(result),
            ]
        )
        if result.has_sources:
            state.web_search_results.append(result)
        result_refs = state.evidence_store.add_web_result(result)
        state.turn_state.record_search(
            tool_name="web_search",
            query=query_text,
            evidence_refs=result_refs,
            searched_at=result.searched_at,
            freshness=result.freshness,
            status="ok" if result.has_sources else "no_sources",
        )
        state.telemetry.web_search_count += 1
        self._publish(
            "web_search_completed",
            {
                "query": result.query,
                "source_count": len(result.sources),
                "step": step,
                "max_steps": state.budget.max_steps,
                "cached": False,
            },
        )
        self._collect_web_search_image_selections(state, result)
        tool_payload = _budgeted_web_search_result_tool_payload(
            result,
            state.evidence_context_budget,
            telemetry=state.telemetry,
        )
        tool_payload = self._with_generated_ui_images(state, tool_payload)
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                tool_payload,
            )
        )

    # このターンで選定済みの検索画像を、生成UIが番号で参照できる一覧としてツール結果へ添える。
    # 生成UIを出さないターン（利用者が不要と書いた、または判定が NONE）では添えない。
    # Add the images selected so far this turn to the tool result as a list a generated UI can
    # reference by number. Turns that produce no generated UI (the user refused one, or the
    # decision is NONE) get no list.
    def _with_generated_ui_images(
        self,
        state: ChatTurnRunState,
        tool_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._explicit_ui_opt_out or str(self._ui_mode or "").strip().upper() == "NONE":
            return tool_payload
        catalog = build_generated_ui_image_catalog(state.selected_web_search_images)
        if not catalog:
            return tool_payload
        return {**tool_payload, GENERATED_UI_IMAGES_TOOL_KEY: catalog}

    # 月間上限に達した検索を、ターンを落とさずに記録・通知するフェーズ。
    # The phase that records and announces a quota-exhausted search without failing the turn.
    def _report_web_search_quota_exceeded(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        exc: WebSearchQuotaExceededError,
        *,
        query_text: str,
        step: int,
    ) -> None:
        message = (
            f"Web検索の月間上限（全体 {exc.limit} 回）に達しました。"
            "検索なしで回答を続けます。"
        )
        logger.warning(
            "Web search quota exceeded mid-turn (limit=%s, retry_after_seconds=%s); "
            "continuing the turn without this search.",
            exc.limit,
            exc.retry_after_seconds,
            extra=self._telemetry.as_log_extra(),
        )
        state.web_search_trace_steps.append(
            search_failed_step(
                query_text,
                reason="月間上限に達したため検索結果を取得できませんでした。",
            )
        )
        state.suppress_next_generation_started = True
        self._publish(
            "web_search_failed",
            {
                "query": query_text,
                "code": WEB_SEARCH_ERROR_QUOTA_EXCEEDED,
                "message": message,
                "retry_after_seconds": exc.retry_after_seconds,
                "step": step,
                "max_steps": state.budget.max_steps,
            },
        )
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                {
                    "status": "quota_exceeded",
                    "message": message,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            )
        )
        state.turn_state.record_search(
            tool_name="web_search",
            query=query_text,
            status="quota_exceeded",
        )

    # 検索リクエスト自体が失敗した場合に、取得済みの情報で続行させるフェーズ。
    # The phase that keeps the turn going on already gathered evidence when a search request fails.
    def _report_web_search_failure(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        *,
        query_text: str,
        step: int,
    ) -> None:
        logger.exception("Brave search via tool call failed.")
        state.web_search_trace_steps.append(
            search_failed_step(
                query_text,
                reason="検索リクエストに失敗したため、取得済みの情報で回答を続けました。",
            )
        )
        state.suppress_next_generation_started = True
        self._publish(
            "web_search_failed",
            {
                "query": query_text,
                "code": WEB_SEARCH_ERROR_REQUEST_FAILED,
                "message": "Web検索に失敗しました。検索なしで回答を続けます。",
                "step": step,
                "max_steps": state.budget.max_steps,
            },
        )
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                {
                    "status": "failed",
                    "message": "Web search failed.",
                },
            )
        )
        state.turn_state.record_search(
            tool_name="web_search",
            query=query_text,
            status="failed",
        )
