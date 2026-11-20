# 「回答までのステップ」（回答の実行記録）の各ステップを作り、回答パーツ用の構造化データへまとめる。
# 各ステップは自分自身が参照したソースを保持するため、1回目の検索でも追加検索でも
# 同じように「参照したWebサイト」を展開できる。データの形と上限は answer_trace.py、描画は画面側が持つ。
# Builds the steps of the "steps to the answer" (the answer's execution record) and gathers them
# into the structured data of an answer part. Every step carries the sources it used, so the first
# search and any follow-up searches all expand their own "referenced websites" panel. The shape and
# limits of the data belong to answer_trace.py, and rendering to the screen.

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .answer_trace import (
    ANSWER_TRACE_STEP_KINDS,
    ANSWER_TRACE_VERSION,
    DEFAULT_ANSWER_TRACE_STEP_KIND,
    STEP_BADGE_MAX_CHARS,
    STEP_CHIP_MAX_CHARS,
    STEP_DETAIL_MAX_CHARS,
    STEP_QUERY_MAX_CHARS,
    STEP_TITLE_MAX_CHARS,
    normalize_answer_trace,
)
from .selected_reference_context import (
    MEMORY_SEARCH_SOURCE,
    PERSONAL_KNOWLEDGE_SOURCE,
    SelectedReferenceLookupTrace,
)
from .web_search import (
    WebSearchResult,
    WebSearchSource,
    normalize_text,
    source_hostname_label,
)

# 旧形式（title/detailのみ）のステップから種別を推定するための接頭辞。
# 「メモとマイコンテキスト」は画面名を「記憶」に改める前に保存された題名なので、読み取り用に残す。
# Prefixes used to infer a kind from legacy steps that only carry title/detail.
# "メモとマイコンテキスト" is the title saved before the screen name became "記憶"; it stays so old data is still read.
_TITLE_KIND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("メモと記憶", "knowledge"),
    ("メモとマイコンテキスト", "knowledge"),
    ("メモを検索", "knowledge"),
    ("記憶を検索", "knowledge"),
    ("共有プロンプト", "prompt"),
    ("検索が必要", "decide"),
    ("検索結果を再利用", "reuse"),
    ("Web検索を試行", "warning"),
    ("追加検索", "search"),
    ("Web検索", "search"),
    ("重要なページ", "read"),
    ("リンクをたどって", "follow"),
    ("検索結果を確認", "review"),
    ("回答を作成", "answer"),
)

# 鮮度指定のユーザー向けラベル
# User-facing labels for the freshness filter.
_FRESHNESS_LABELS: dict[str, str] = {
    "pd": "24時間以内",
    "pw": "1週間以内",
    "pm": "1か月以内",
    "py": "1年以内",
}

# ステップ要約に並べるドメインチップの最大数
# Maximum number of domain chips shown in a step summary.
_MAX_DOMAIN_CHIPS = 3


@dataclass(frozen=True)
class TraceStep:
    """回答トレースの1ステップ。sources を持つステップは展開できる。

    One step of the answer trace; a step that carries sources can be expanded.
    """

    title: str
    detail: str = ""
    kind: str = DEFAULT_ANSWER_TRACE_STEP_KIND
    query: str = ""
    badge: str = ""
    chips: tuple[str, ...] = ()
    sources: WebSearchResult | None = None
    # 実行中のステップだけが "running" を持つ。空なら種類から決まる（warning は失敗、それ以外は完了）。
    # Only a step still in progress carries "running"; empty means the kind decides (warning is failed, anything else done).
    status: str = ""


def _hostnames(result: WebSearchResult | None) -> list[str]:
    # 検索結果から重複のないホスト名を出現順に取り出す
    # Collect unique hostnames from a result in their original order.
    if result is None:
        return []
    seen: list[str] = []
    for source in result.sources:
        hostname = source.hostname.strip().removeprefix("www.")
        if hostname and hostname not in seen:
            seen.append(hostname)
    return seen


def _domain_chips(result: WebSearchResult | None) -> tuple[str, ...]:
    # 要約行に並べるドメインチップ（上限を超えた分は「+N」に畳む）を作る
    # Build the domain chips for a summary row, folding the overflow into "+N".
    hostnames = _hostnames(result)
    if not hostnames:
        return ()
    chips = hostnames[:_MAX_DOMAIN_CHIPS]
    remainder = len(hostnames) - len(chips)
    if remainder > 0:
        chips = [*chips, f"+{remainder}"]
    return tuple(chips)


def _freshness_label(result: WebSearchResult | None) -> str:
    # 鮮度指定をユーザー向けラベルへ変換する
    # Translate the freshness filter into a user-facing label.
    if result is None:
        return ""
    return _FRESHNESS_LABELS.get(result.freshness.strip(), "")


# 日本語: 検索結果が持つソースの件数。結果が無ければ 0。
# English: Number of sources in a result; 0 when there is no result.
def _source_count(result: WebSearchResult | None) -> int:
    return len(result.sources) if result is not None else 0


def search_step(
    result: WebSearchResult,
    *,
    additional: bool = False,
    cached: bool = False,
) -> TraceStep:
    # 実際にWeb検索を行った（または同条件の結果を再利用した）ステップ
    # The step that ran a web search, or reused a result for the same conditions.
    count = _source_count(result)
    freshness = _freshness_label(result)
    scope = f"{freshness}の情報に絞り込んで" if freshness else ""
    if cached:
        title = "検索結果を再利用"
        detail = f"同じ検索条件の結果がこのターンに残っていたため、{count}件をそのまま使い回しました。"
        kind = "reuse"
    else:
        title = "追加検索" if additional else "Web検索"
        lead = "不足していた情報を補うため、" if additional else "回答の根拠を集めるため、"
        detail = f"{lead}{scope}検索を実行し、{count}件の候補ページを取得しました。"
        kind = "search"
    return TraceStep(
        title=title,
        detail=detail,
        kind=kind,
        query=result.query,
        badge=f"{count}件" if count else "",
        chips=_domain_chips(result),
        sources=result,
    )


def _read_sources(result: WebSearchResult | None, *, followed: bool) -> list[WebSearchSource]:
    # 本文を読み込めたソースを、検索結果ページ（depth 0）と
    # リンクをたどって到達したページ（depth 1以上）に振り分ける。
    # Split sources whose body was read into search-result pages (depth 0)
    # and pages reached by following links (depth 1+).
    if result is None:
        return []
    return [
        source
        for source in result.sources
        if source.page_text and (source.link_depth >= 1) == followed
    ]


def _sources_only(result: WebSearchResult, sources: Sequence[WebSearchSource]) -> WebSearchResult:
    # 対象ソースだけを持つ結果を作り、ステップの「参照したWebサイト」を絞り込む
    # Build a result carrying only the given sources so a step's panel lists just those.
    return replace(result, sources=tuple(sources))


def page_read_step(result: WebSearchResult | None) -> TraceStep | None:
    # 検索結果ページの本文まで読み込めた場合のステップ。
    # リンクをたどって到達したページは deep_read_step が受け持つ。
    # The step for search-result pages whose body was read.
    # Pages reached by following links belong to deep_read_step instead.
    read_sources = _read_sources(result, followed=False)
    if result is None or not read_sources:
        return None
    hostnames = [
        source.hostname.strip().removeprefix("www.") for source in read_sources if source.hostname
    ]
    lead = f"「{hostnames[0]}」など" if hostnames else ""
    return TraceStep(
        title="重要なページを精読",
        detail=(
            f"検索結果のうち{lead}{len(read_sources)}件は、スニペットではなくページ本文まで"
            "読み込んで根拠にしました。"
        ),
        kind="read",
        badge=f"{len(read_sources)}件",
        chips=_domain_chips(_sources_only(result, read_sources)),
        sources=_sources_only(result, read_sources),
    )


def deep_read_step(result: WebSearchResult | None) -> TraceStep | None:
    # 検索結果ページからリンクをたどって深掘りした場合のステップ。
    # 検索結果には出てこなかったページなので、精読ステップとは分けて示す。
    # The step for pages reached by following links out of the search results.
    # They never appeared in the results themselves, so they get their own step.
    followed_sources = _read_sources(result, followed=True)
    if result is None or not followed_sources:
        return None
    max_depth = max(source.link_depth for source in followed_sources)
    origins: list[str] = []
    for source in followed_sources:
        origin = source_hostname_label(source.linked_from_url)
        if origin and origin not in origins:
            origins.append(origin)
    lead = f"「{origins[0]}」など検索結果のページから" if origins else "検索結果のページから"
    return TraceStep(
        title="リンクをたどって深掘り",
        detail=(
            f"{lead}参照先のリンクをたどり、最大{max_depth}階層先までの{len(followed_sources)}件を"
            "追加で読み込んで根拠にしました。"
        ),
        kind="follow",
        badge=f"{len(followed_sources)}件・最大{max_depth}階層",
        chips=_domain_chips(_sources_only(result, followed_sources)),
        sources=_sources_only(result, followed_sources),
    )


def page_reading_steps(result: WebSearchResult | None) -> list[TraceStep]:
    # ページ本文の取得に関するステップを、実際に起きた順（精読 → リンク深掘り）で返す。
    # 該当するページが無い段階はステップを出さない。
    # Return the page-reading steps in the order they happened: read the result
    # pages, then follow their links. Stages without any page emit no step.
    return [step for step in (page_read_step(result), deep_read_step(result)) if step is not None]


def review_step(result: WebSearchResult | None, *, reused: bool = False) -> TraceStep:
    # 取得した検索結果を吟味したステップ
    # The step where the retrieved results were reviewed.
    count = _source_count(result)
    if reused:
        detail = f"再利用した{count}件で質問に答えられるか読み直し、不足がないか確認しました。"
    elif count:
        detail = (
            f"取得した{count}件を読み比べ、質問に直接答えている記述と、"
            "根拠として弱い記述を切り分けました。"
        )
    else:
        detail = "取得した情報が回答の根拠として使えるかを確認しました。"
    return TraceStep(title="検索結果を確認", detail=detail, kind="review")


# 実行中のステップと結果のステップは同じ題名を使う。同じ ID のまま状態だけが変わったように見せるため。
# A running step and its result share one title, so the step appears to change only its status under the same id.
_PERSONAL_KNOWLEDGE_STEP_TITLE = "メモを検索"
_MEMORY_STEP_TITLE = "記憶を検索"
_SHARED_PROMPT_STEP_TITLE = "共有プロンプトを検索"
_KNOWN_PAGE_READ_STEP_TITLE = "参照先のページ本文を確認"
# 打ち切られて実行中のまま残ったステップに付ける説明。
# The description given to a step that was cut off while still running.
_INTERRUPTED_STEP_DETAIL = "完了を確認できなかったため、取得済みの情報で回答を続けました。"


def running_step(title: str, detail: str, *, kind: str, query: str = "") -> TraceStep:
    # 始めたがまだ結果の出ていないステップ。終わったら、結果を持つステップへ置き換える。
    # A step that has started and has no result yet; it is replaced by the step carrying the result once it ends.
    return TraceStep(title=title, detail=detail, kind=kind, query=query, badge="実行中", status="running")


def running_search_step(query: str, *, additional: bool = False) -> TraceStep:
    # Web検索を実行している間のステップ
    # The step shown while a web search is running.
    return running_step(
        "追加検索" if additional else "Web検索",
        "検索を実行しています。",
        kind="search",
        query=query,
    )


def running_reference_step(source: str, query: str) -> TraceStep:
    # メモ、記憶、または共有プロンプトを検索している間のステップ
    # The step shown while memos, memory or shared prompts are being searched.
    if source == MEMORY_SEARCH_SOURCE:
        # 記憶の検索では、モデルが記憶の内容から作った検索語になりうるので、検索語を載せない（共有リンクやルームの複製にも残るため）。
        # The model's memory query can be built from memory content, so it is not shown
        # (the step also survives in shared links and room copies).
        return running_step(_MEMORY_STEP_TITLE, "保存済みの記憶を検索しています。", kind="knowledge")
    if source == PERSONAL_KNOWLEDGE_SOURCE:
        return running_step(
            _PERSONAL_KNOWLEDGE_STEP_TITLE, "保存済みのメモを検索しています。", kind="knowledge", query=query
        )
    return running_step(_SHARED_PROMPT_STEP_TITLE, "共有プロンプトを検索しています。", kind="prompt", query=query)


def running_known_page_read_step() -> TraceStep:
    # 以前に見つけた URL のページを読み込んでいる間のステップ
    # The step shown while a page behind a previously found URL is being read.
    return running_step(_KNOWN_PAGE_READ_STEP_TITLE, "ページを読み込んでいます。", kind="read")


def known_page_read_step() -> TraceStep:
    # 以前に見つけた URL のページ本文を読めたステップ
    # The step for a page behind a previously found URL whose body was read.
    return TraceStep(
        title=_KNOWN_PAGE_READ_STEP_TITLE,
        detail="以前に見つけたURLから、回答に必要な箇所を読みました。",
        kind="read",
    )


def settle_running_steps(steps: Sequence[TraceStep]) -> list[TraceStep]:
    """実行中のまま残ったステップを、結果を使えなかったステップにする。

    回答を確定する時点で終わっていないステップは、障害で打ち切られたもの。完了したようには見せない。

    Turn every step still marked as running into one whose result could not be used.

    A step that has not ended when the answer is settled was cut off by a failure, and must not look completed.
    """
    return [
        replace(
            step,
            kind="warning",
            status="",
            detail=_INTERRUPTED_STEP_DETAIL,
            badge="",
            chips=(),
            sources=None,
        )
        if step.status == "running"
        else step
        for step in steps
    ]


def settle_running_answer_trace(trace: dict[str, Any] | None) -> dict[str, Any] | None:
    """配信済みの実行記録のうち、実行中のまま残ったステップを、結果を使えなかったステップにする。

    本文が確定する前にターンが終わる経路（停止で未確定の本文を保存する、承認カードだけを残す）では、画面に
    配信済みの記録をそのまま保存する。そのとき実行中のステップを完了したようには残さない。

    Turn every step still running in an already published record into one whose result could not be used.

    When a turn ends before any body is confirmed (a stop that saves unconfirmed text, a reply that keeps only
    approval cards), the record already on screen is what gets stored, and a running step must not be kept
    as if it had completed.
    """
    if trace is None or not any(step.get("status") == "running" for step in trace["steps"]):
        return trace
    return normalize_answer_trace(
        {
            **trace,
            "steps": [
                {**step, "kind": "warning", "status": "failed", "detail": _INTERRUPTED_STEP_DETAIL, "badge": "", "chips": [], "sources": []}
                if step.get("status") == "running"
                else step
                for step in trace["steps"]
            ],
        }
    )


def search_failed_step(query: str = "", *, reason: str = "") -> TraceStep:
    # 検索を試みたが結果を使えなかったステップ
    # The step for a search attempt whose result could not be used.
    return TraceStep(
        title="Web検索を試行",
        detail=reason or "検索結果を回答に使える形では取得できませんでした。",
        kind="warning",
        query=query,
    )


def selected_reference_step(
    source: str,
    payload: dict[str, Any],
    *,
    query: str = "",
) -> TraceStep:
    """メモ、記憶、または共有プロンプトの検索に対するトレースのステップを作る。

    status が failed / unavailable なら警告、overview なら保存済みのメモを棚卸しとして渡したステップになる。

    Build a trace step for memo, memory or shared-prompt lookup.
    """
    status = str(payload.get("status") or "")
    resolved_query = str(payload.get("query") or query)

    if source == PERSONAL_KNOWLEDGE_SOURCE and status == "overview":
        # 一致0件のあと、直近のメモの見出しを棚卸しとして渡したステップ。
        # The step where a zero-match lookup handed over an inventory of recent memo titles.
        total = int(payload.get("recent_memo_count") or 0)
        return TraceStep(
            title="保存済みのメモを確認",
            detail=f"検索条件に一致するものは無かったため、最近のメモの見出しを{total}件読み込み、回答の材料にしました。",
            kind="knowledge",
            query=resolved_query,
            badge=f"{total}件",
            chips=(f"最近のメモ {total}件",) if total else (),
        )

    if source == MEMORY_SEARCH_SOURCE:
        # 記憶の検索は、件数とラベルだけを残す。検索語も記憶の文面も載せない。
        # The memory step keeps only the count and a label: neither the query nor any memory text.
        total = int(payload.get("memory_count") or 0)
        resolved_query = ""
        title = _MEMORY_STEP_TITLE
        kind = "knowledge"
        chips = (f"記憶 {total}件",) if total else ()
        success_detail = (
            f"保存済みの記憶から、回答に関連するものを{total}件読み込みました。"
            if total
            else "保存済みの記憶を検索しましたが、該当するものはありませんでした。"
        )
    elif source == PERSONAL_KNOWLEDGE_SOURCE:
        total = int(payload.get("memo_count") or 0)
        title = _PERSONAL_KNOWLEDGE_STEP_TITLE
        kind = "knowledge"
        chips = (f"メモ {total}件",) if total else ()
        success_detail = (
            f"保存済みのメモから、回答に関連する情報を{total}件読み込みました。"
            if total
            else "保存済みのメモを検索しましたが、該当する情報はありませんでした。"
        )
    else:
        total = int(payload.get("prompt_count") or 0)
        title = _SHARED_PROMPT_STEP_TITLE
        kind = "prompt"
        chips = (f"共有プロンプト {total}件",) if total else ()
        success_detail = (
            f"公開されている共有プロンプトから、回答に関連するものを{total}件読み込みました。"
            if total
            else "共有プロンプトを検索しましたが、該当するものはありませんでした。"
        )

    if status in {"failed", "unavailable"}:
        return TraceStep(
            title=title,
            detail=(
                "参照元を利用できなかったため、検索結果を回答へ追加できませんでした。"
                if status == "unavailable"
                else "検索に失敗したため、取得済みの情報で回答を続けました。"
            ),
            kind="warning",
            query=resolved_query,
        )

    return TraceStep(
        title=title,
        detail=success_detail,
        kind=kind,
        query=resolved_query,
        badge=f"{total}件",
        chips=chips,
    )


# 日本語: 選ばれた参照元の検索結果を、それぞれトレースのステップに変換する。
# English: Convert each selected-reference lookup result into a trace step.
def selected_reference_steps(
    traces: Sequence[SelectedReferenceLookupTrace] | None,
) -> list[TraceStep]:
    return [
        selected_reference_step(trace.source, trace.payload, query=trace.query)
        for trace in traces or ()
    ]


def answer_step(results: Sequence[WebSearchResult] | None = None) -> TraceStep:
    # 収集した情報をまとめて回答を書いたステップ
    # The step that composed the answer from everything gathered.
    searches = len(results or [])
    unique_sources = len({source.url for result in results or [] for source in result.sources})
    if unique_sources:
        detail = (
            f"{searches}回の検索で集めた{unique_sources}件の情報と会話の文脈を突き合わせ、"
            "出典を示しながら回答を作成しました。"
        )
    else:
        detail = "会話の文脈をもとに回答を作成しました。"
    return TraceStep(title="回答を作成", detail=detail, kind="answer")


def _infer_kind(title: str) -> str:
    # 旧形式のステップから種別を推定する
    # Infer a kind for legacy steps that carry no explicit kind.
    for prefix, kind in _TITLE_KIND_PREFIXES:
        if title.startswith(prefix):
            return kind
    return DEFAULT_ANSWER_TRACE_STEP_KIND


# 日本語: 文字数の上限を適用して正規化する。題名が空のステップは捨てて、未知の種別は既定の種別に寄せる。
# English: Normalize with the length caps applied; steps without a title are dropped and unknown kinds fall back to the default.
def _coerce_step(step: Any) -> TraceStep | None:
    # dict形式のステップ（旧呼び出し側・テスト）も受け付けて正規化する
    # Accept and normalize dict-shaped steps from legacy callers and tests.
    if isinstance(step, TraceStep):
        source = step
    elif isinstance(step, dict):
        raw_sources = step.get("sources")
        source = TraceStep(
            title=str(step.get("title", "")),
            detail=str(step.get("detail", "")),
            kind=str(step.get("kind", "")) or _infer_kind(str(step.get("title", ""))),
            query=str(step.get("query", "")),
            badge=str(step.get("badge", "")),
            chips=tuple(str(chip) for chip in step.get("chips", ()) or ()),
            sources=raw_sources if isinstance(raw_sources, WebSearchResult) else None,
        )
    else:
        return None

    title = normalize_text(source.title, max_chars=STEP_TITLE_MAX_CHARS)
    if not title:
        return None
    kind = source.kind if source.kind in ANSWER_TRACE_STEP_KINDS else DEFAULT_ANSWER_TRACE_STEP_KIND
    return TraceStep(
        title=title,
        detail=normalize_text(source.detail, max_chars=STEP_DETAIL_MAX_CHARS),
        kind=kind,
        query=normalize_text(source.query, max_chars=STEP_QUERY_MAX_CHARS),
        badge=normalize_text(source.badge, max_chars=STEP_BADGE_MAX_CHARS),
        chips=tuple(
            chip for chip in (normalize_text(chip, max_chars=STEP_CHIP_MAX_CHARS) for chip in source.chips) if chip
        ),
        sources=source.sources,
        status=source.status if source.status == "running" else "",
    )


def _summary_detail(steps: Sequence[TraceStep], source_total: int) -> str:
    # 折りたたみ時にも中身が想像できる1行サマリ
    # A one-line summary that hints at the content while collapsed.
    search_count = sum(1 for step in steps if step.kind in {"search", "reuse"})
    read_count = sum(1 for step in steps if step.kind == "read")
    follow_count = sum(1 for step in steps if step.kind == "follow")
    memory_count = sum(1 for step in steps if step.kind == "knowledge" and step.title == _MEMORY_STEP_TITLE)
    knowledge_count = sum(1 for step in steps if step.kind == "knowledge") - memory_count
    prompt_count = sum(1 for step in steps if step.kind == "prompt")
    parts: list[str] = []
    if search_count:
        parts.append(f"Web検索{search_count}回")
    if source_total:
        parts.append(f"参照サイト{source_total}件")
    if read_count:
        parts.append("本文精読あり")
    if follow_count:
        parts.append("リンク深掘りあり")
    if knowledge_count:
        parts.append("メモ検索あり")
    if memory_count:
        parts.append("記憶検索あり")
    if prompt_count:
        parts.append("共有プロンプト検索あり")
    return " · ".join(parts)


def _trace_source(source: WebSearchSource) -> dict[str, Any] | None:
    # 出典 1 件を、画面がリンク・favicon・たどった階層を描ける形にする。URL の無い出典は出さない。
    # Shape one source so the screen can draw its link, favicon and followed depth; a source without a URL is skipped.
    url = source.url.strip()
    if not url:
        return None
    hostname = source.hostname.strip()
    title = source.title.strip()
    return {
        "url": url,
        "title": title or url,
        "hostname": hostname,
        "favicon_url": source.favicon_url.strip(),
        "fallback_label": (hostname or title or url).removeprefix("www.")[:1].upper() or "?",
        "link_depth": source.link_depth,
        "linked_from": source_hostname_label(source.linked_from_url) if source.link_depth >= 1 else "",
    }


def _trace_sources(result: WebSearchResult | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    return [item for item in (_trace_source(source) for source in result.sources) if item is not None]


def _trace_step(step: TraceStep, sources: list[dict[str, Any]]) -> dict[str, Any]:
    # 実行中のステップはそのまま渡す。結果を回答に使えなかったステップ（warning）は失敗、それ以外は完了済み。
    # A running step is handed over as such. A step whose result could not be used (warning) is failed; every other one is done.
    return {
        "kind": step.kind,
        "status": step.status or ("failed" if step.kind == "warning" else "done"),
        "title": step.title,
        "detail": step.detail,
        "query": step.query,
        "badge": step.badge,
        "chips": list(step.chips),
        "sources": sources,
    }


def _unique_source_total(source_lists: Iterable[Sequence[dict[str, Any]]]) -> int:
    # 同じ出典が複数ステップに出るため、URL で重複を除いて数える
    # The same source appears under several steps, so count distinct URLs.
    return len({source["url"] for sources in source_lists for source in sources})


def build_answer_trace(
    result: WebSearchResult | None = None,
    *,
    steps: Sequence[Any] | None = None,
) -> dict[str, Any] | None:
    """「回答までのステップ」を、回答パーツとして保存・配信する構造化データにする。出すものが無ければ ``None``。

    どのステップも出典を持たないときは、``result`` の出典を「参照したWebサイト」のステップとして末尾に足す。

    Build the "steps to the answer" as the structured data stored and delivered in an answer part;
    ``None`` when there is nothing to show.

    When no step carries sources, the sources of ``result`` are appended as a "referenced websites" step.
    """
    normalized_steps = [
        coerced for coerced in (_coerce_step(step) for step in steps or []) if coerced is not None
    ]
    trace_steps = [_trace_step(step, _trace_sources(step.sources)) for step in normalized_steps]
    if result is not None and not any(step.sources is not None for step in normalized_steps):
        fallback_sources = _trace_sources(result)
        if fallback_sources:
            query = result.query.strip()
            trace_steps.append(
                _trace_step(
                    TraceStep(
                        title="参照したWebサイト",
                        detail=f"「{query}」の検索結果を回答の根拠に使いました。" if query else "",
                        kind="search",
                        badge=f"{len(fallback_sources)}件",
                    ),
                    fallback_sources,
                )
            )
    if not trace_steps:
        return None
    source_total = _unique_source_total(step["sources"] for step in trace_steps)
    return normalize_answer_trace(
        {
            "version": ANSWER_TRACE_VERSION,
            # 要約には、終わったステップだけを数える。実行中の検索を「検索 1 回」と見せない。
            # The summary counts finished steps only, so a search still running does not read as one search done.
            "summary": _summary_detail([step for step in normalized_steps if step.status != "running"], source_total),
            "steps": trace_steps,
        }
    )
