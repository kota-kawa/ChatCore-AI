"""1ターン分の生成ループが持ち回る可変状態をまとめたモジュール。

Holds the mutable per-turn state that the chat generation loop carries between phases.

このモジュールは状態の置き場だけを担い、ループの制御や外部呼び出しは持たない。
ChatGenerationJob の各フェーズはこの1つのオブジェクトを受け渡すことで、
10個以上の引数を引き回さずに済む。
This module only owns the state container; it never drives the loop or calls out to
providers. Each ChatGenerationJob phase passes this single object around instead of
threading a dozen parameters through every helper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .chat_agent_budget import AgentStepBudget
from .chat_evidence_store import EvidenceStore
from .chat_generation_telemetry import ChatGenerationTelemetry
from .chat_turn_state import TurnStateUpdateFilter
from .research_state import TurnState
from .web_search import (
    WebEvidenceContextBudget,
    WebPageFetchBudget,
    WebSearchResult,
)
from .web_search_trace import TraceStep


# 1ターンの生成ループが横断的に読み書きする状態。フェーズ間をまたぐ値だけを持つ。
# The state a single generation turn reads and writes across phases; only values that
# cross a phase boundary live here.
@dataclass
class ChatTurnRunState:
    # 配信済み本文チャンク（ジョブ側のリストと同一オブジェクトを共有する）。
    # Published body chunks; the very same list object the job holds for cancellation.
    chunks: list[str]
    # このターンのテレメトリ集計（ジョブ側と同一オブジェクト）。
    # This turn's telemetry accumulator, shared with the job instance.
    telemetry: ChatGenerationTelemetry
    # LLM判断回数とツール実行回数の予算。
    # Budget for model decisions and tool executions.
    budget: AgentStepBudget
    # ページ本文取得の予算。
    # Budget for fetching page bodies during web search.
    page_fetch_budget: WebPageFetchBudget
    # プロンプトへ載せる根拠テキストの文字数予算。
    # Character budget for the evidence text that enters the prompt.
    evidence_context_budget: WebEvidenceContextBudget
    # 収集済み根拠の保管庫（再取得ツールもここを引く）。
    # Store of collected evidence; the re-read tool also draws from it.
    evidence_store: EvidenceStore
    # モデルへ投影する調査状態。
    # The research state projected into each model decision.
    turn_state: TurnState
    # 投影のベースとなる会話履歴のスナップショット。
    # Snapshot of the conversation history used as the projection base.
    turn_base_messages: list[dict[str, Any]]
    # 最新のユーザー依頼テキスト（画像選定と言語ヒントに使う）。
    # The latest user request text, used for image selection and language hints.
    latest_user_message: str
    # 選定済みの検索画像（ジョブ側のリストと同一オブジェクトを共有する）。
    # Selected search images; the same list object the job holds for cancellation.
    selected_web_search_images: list[dict[str, str]]
    # 継続生成中に内部状態の封筒を取り除くフィルタ。
    # Filter that strips internal state envelopes during answer continuation.
    continuation_state_filter: TurnStateUpdateFilter

    # このターンで取得したWeb検索結果と、同一条件の再検索を避けるキャッシュ。
    # Web search results gathered this turn, plus a cache keyed by search conditions.
    web_search_results: list[WebSearchResult] = field(default_factory=list)
    web_search_results_by_key: dict[tuple[str, str, str], WebSearchResult] = field(
        default_factory=dict
    )
    # 回答冒頭に前置する調査トレースのステップ列。
    # Trace steps rendered ahead of the answer body.
    web_search_trace_steps: list[TraceStep] = field(default_factory=list)
    # 次の判断へ渡す直近のツール呼び出しと結果だけの会話断片。
    # The newest tool call and its result, the only tool history sent to the next decision.
    current_messages: list[dict[str, Any]] = field(default_factory=list)
    # モデルへ提示するツール定義。
    # Tool definitions offered to the model.
    configured_tools: list[dict[str, Any]] = field(default_factory=list)
    # 回答を書いた判断の要求内容（生成UIの再試行に使う）。
    # The request that produced the answer, reused when retrying generated UI.
    answer_context_messages: list[dict[str, Any]] | None = None
    # 回答が途中で終わった原因の例外（None なら完走）。
    # Why the answer ended early; None means it finished.
    final_answer_incomplete: BaseException | None = None
    # 継続生成の回数。
    # Number of continuation passes performed.
    continuation_count: int = 0
    # 直前に配信した UI パーツ更新の署名（同一内容の再配信を防ぐ）。
    # Signature of the last published UI parts update, to suppress duplicates.
    last_streaming_parts_signature: str | None = None
    # 引用チップ判定が確定するまで保留しているストリーム末尾。
    # Stream tail held back until the citation-chip boundary is decidable.
    streaming_citation_buffer: str = ""
    # これまでにユーザーへ配信した表示本文（画像挿入位置の基準）。
    # Display text already delivered to the user; the anchor for image offsets.
    streamed_display_text: str = ""
    # 既に露出した検索画像の添字と挿入オフセット。
    # Indices and insertion offsets of search images already revealed.
    revealed_image_indices: list[int] = field(default_factory=list)
    revealed_image_offsets: list[int] = field(default_factory=list)
    # 次のループで generation_started を再送しないための抑制フラグ。
    # Suppresses a duplicate generation_started event on the next loop pass.
    suppress_next_generation_started: bool = False
    # 入力上限で拒否された後、最小構成へ切り替えたことを示すフラグ。
    # Set once an input-limit rejection switched the request to its minimal shape.
    minimal_context_required: bool = False
    # ツールスキーマ拒否からの再構築を1度だけに限るフラグ。
    # Limits the tool-schema rejection recovery to a single replay.
    tool_schema_recovery_attempted: bool = False
    # 本文ゼロの判断に対する回答のみ再試行を1度だけに限るフラグ。
    # Limits the answer-only retry after an empty decision to a single replay.
    empty_answer_recovery_attempted: bool = False


# 1回のモデル判断ストリームの結末。停止・再試行・判断確定の3つだけを表す。
# The outcome of streaming one model decision: stopped, replay, or a settled decision.
ModelDecisionOutcome = Literal["stopped", "replay", "decided"]


# モデル判断1回の結果。ツール呼び出しと本文チャンクは判断が確定したときだけ入る。
# The result of one model decision; tool calls and body chunks are filled in only when
# the decision actually settled.
@dataclass(frozen=True)
class ModelDecision:
    outcome: ModelDecisionOutcome
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    step_chunks: list[str] = field(default_factory=list)
