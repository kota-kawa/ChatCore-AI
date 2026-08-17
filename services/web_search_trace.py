# 「回答までのステップ」UI（回答生成トレース）のデータ構造とHTML組み立てを担当する。
# 各ステップは自分自身が参照したソースを保持するため、1回目の検索でも追加検索でも
# 同じように「参照したWebサイト」を展開できる。
# Owns the data model and HTML assembly for the answer-trace UI ("steps to the answer").
# Every step carries the sources it used, so the first search and any follow-up
# searches all expand their own "referenced websites" panel.

from __future__ import annotations

from dataclasses import dataclass, replace
from html import escape
from typing import Any, Iterable, Sequence

from .selected_reference_context import (
    PERSONAL_KNOWLEDGE_SOURCE,
    SelectedReferenceLookupTrace,
)
from .web_search import (
    WebSearchResult,
    WebSearchSource,
    build_web_search_source_items,
    normalize_text,
    source_hostname_label,
)

# ステップ見出し・説明文の最大文字数
# Maximum lengths for step titles and descriptions.
STEP_TITLE_MAX_CHARS = 120
STEP_DETAIL_MAX_CHARS = 260
STEP_QUERY_MAX_CHARS = 120

# ステップ種別ごとのアイコン（Bootstrap Icons）。未知の種別は既定のアイコンへ寄せる。
# Bootstrap Icons per step kind; unknown kinds fall back to the default icon.
_STEP_ICONS: dict[str, str] = {
    "decide": "bi-compass",
    "search": "bi-search",
    "reuse": "bi-arrow-repeat",
    "read": "bi-file-earmark-text",
    "follow": "bi-signpost-split",
    "review": "bi-check2-circle",
    "answer": "bi-stars",
    "warning": "bi-exclamation-triangle",
    "knowledge": "bi-journal-text",
    "prompt": "bi-card-text",
    "info": "bi-record-circle",
}
_DEFAULT_STEP_KIND = "info"

# 旧形式（title/detailのみ）のステップから種別を推定するための接頭辞。
# Prefixes used to infer a kind from legacy steps that only carry title/detail.
_TITLE_KIND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("メモとマイコンテキスト", "knowledge"),
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
    """回答トレースの1ステップ。sources を持つステップは展開できる。"""

    title: str
    detail: str = ""
    kind: str = _DEFAULT_STEP_KIND
    query: str = ""
    badge: str = ""
    chips: tuple[str, ...] = ()
    sources: WebSearchResult | None = None


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


def _source_count(result: WebSearchResult | None) -> int:
    return len(result.sources) if result is not None else 0


def decision_step(result: WebSearchResult | None = None) -> TraceStep:
    # 検索の要否を判断したステップ
    # The step where the assistant decided a search was needed.
    freshness = _freshness_label(result)
    detail = "質問の内容から、手元の知識だけでは足りず最新情報が必要だと判断しました。"
    if freshness:
        detail = f"{detail[:-1]}（{freshness}の情報を優先）。"
    return TraceStep(title="検索が必要か判断", detail=detail, kind="decide")


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


def context_added_step(result: WebSearchResult | None) -> TraceStep:
    # 検索結果を回答用の文脈へ取り込んだステップ
    # The step that folded the search results into the answering context.
    count = _source_count(result)
    return TraceStep(
        title="検索結果を回答の文脈へ追加",
        detail=(
            f"{count}件の抜粋を回答用の参照データとして読み込みました。"
            if count
            else "取得した抜粋を回答用の参照データとして読み込みました。"
        ),
        kind="review",
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
    """Build a trace step for memo/My Context or shared-prompt lookup."""
    status = str(payload.get("status") or "")
    resolved_query = str(payload.get("query") or query)

    if source == PERSONAL_KNOWLEDGE_SOURCE:
        memo_count = int(payload.get("memo_count") or 0)
        fact_count = int(payload.get("context_fact_count") or 0)
        total = memo_count + fact_count
        title = "メモとマイコンテキストを検索"
        kind = "knowledge"
        chips = tuple(
            label
            for count, label in (
                (memo_count, f"メモ {memo_count}件"),
                (fact_count, f"マイコンテキスト {fact_count}件"),
            )
            if count
        )
        success_detail = (
            f"保存済みのメモとマイコンテキストから、回答に関連する情報を{total}件読み込みました。"
            if total
            else "保存済みのメモとマイコンテキストを検索しましたが、該当する情報はありませんでした。"
        )
    else:
        total = int(payload.get("prompt_count") or 0)
        title = "共有プロンプトを検索"
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
    return _DEFAULT_STEP_KIND


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
    kind = source.kind if source.kind in _STEP_ICONS else _DEFAULT_STEP_KIND
    return TraceStep(
        title=title,
        detail=normalize_text(source.detail, max_chars=STEP_DETAIL_MAX_CHARS),
        kind=kind,
        query=normalize_text(source.query, max_chars=STEP_QUERY_MAX_CHARS),
        badge=normalize_text(source.badge, max_chars=24),
        chips=tuple(
            chip for chip in (normalize_text(chip, max_chars=40) for chip in source.chips) if chip
        ),
        sources=source.sources,
    )


def _render_step_marker(kind: str) -> str:
    # タイムラインの丸印とステップ種別アイコン
    # The timeline dot and the icon for the step kind.
    icon = _STEP_ICONS.get(kind, _STEP_ICONS[_DEFAULT_STEP_KIND])
    return (
        f'<span class="web-search-sources__step-marker web-search-sources__step-marker--{escape(kind)}">'
        f'<i class="bi {escape(icon)}"></i>'
        "</span>"
    )


def _render_step_chips(chips: Iterable[str]) -> str:
    # ステップ要約に並べるドメインチップ
    # The domain chips shown under a step summary.
    rendered = [
        f'<span class="web-search-sources__step-chip">{escape(chip)}</span>' for chip in chips
    ]
    if not rendered:
        return ""
    return '<span class="web-search-sources__step-chips">' + "".join(rendered) + "</span>"


def _render_step_main(step: TraceStep, *, toggle_count: int = 0) -> str:
    # ステップ本文（見出し・検索語・説明・チップ・展開ボタン）を組み立てる
    # Build the step body: heading, query, description, chips, and the expand affordance.
    badge = (
        f'<span class="web-search-sources__step-badge">{escape(step.badge)}</span>'
        if step.badge
        else ""
    )
    query = (
        f'<span class="web-search-sources__step-query">{escape(step.query)}</span>'
        if step.query
        else ""
    )
    detail = (
        f'<span class="web-search-sources__step-detail">{escape(step.detail)}</span>'
        if step.detail
        else ""
    )
    toggle = (
        (
            '<span class="web-search-sources__step-toggle">'
            '<i class="bi bi-globe2"></i>'
            '<span class="web-search-sources__step-toggle-label">参照したWebサイト</span>'
            f'<span class="web-search-sources__step-toggle-count">{toggle_count}件</span>'
            '<span class="web-search-sources__step-chevron"><i class="bi bi-chevron-down"></i></span>'
            "</span>"
        )
        if toggle_count
        else ""
    )
    return (
        '<span class="web-search-sources__step-main">'
        '<span class="web-search-sources__step-head">'
        f'<span class="web-search-sources__step-title">{escape(step.title)}</span>'
        f"{badge}"
        "</span>"
        f"{query}"
        f"{detail}"
        f"{_render_step_chips(step.chips)}"
        f"{toggle}"
        "</span>"
    )


def _render_source_panel(source_items: list[str]) -> str:
    # ステップ内に展開される参照Webサイト一覧。
    # 見出しは開閉ボタン側にあるため、パネル内では繰り返さない。
    # The referenced-website list that expands inside a step; the toggle already
    # carries the heading, so it is not repeated here.
    return (
        '<div class="web-search-sources__step-body">'
        '<ul class="web-search-sources__links">' + "".join(source_items) + "</ul>"
        "</div>"
    )


def _render_step(step: TraceStep, source_items: list[str]) -> str:
    # 1ステップ分のHTMLを組み立てる。ソースを持つステップだけ展開可能にする。
    # Render one step; only steps that carry sources become expandable.
    marker = _render_step_marker(step.kind)
    if not source_items:
        return (
            f'<li class="web-search-sources__step web-search-sources__step--{escape(step.kind)}">'
            f"{marker}"
            '<div class="web-search-sources__step-card">'
            f"{_render_step_main(step)}"
            "</div>"
            "</li>"
        )
    return (
        f'<li class="web-search-sources__step web-search-sources__step--{escape(step.kind)}'
        ' web-search-sources__step--has-sources">'
        f"{marker}"
        '<details class="web-search-sources__step-details">'
        '<summary class="web-search-sources__step-summary">'
        f"{_render_step_main(step, toggle_count=len(source_items))}"
        "</summary>"
        f"{_render_source_panel(source_items)}"
        "</details>"
        "</li>"
    )


def _render_fallback_source_step(result: WebSearchResult | None, source_items: list[str]) -> str:
    # どのステップにも紐づかなかったソースを、独立した展開ブロックとして描画する
    # Render sources that belong to no step as a standalone expandable block.
    query = (result.query if result is not None else "").strip()
    step = TraceStep(
        title="参照したWebサイト",
        detail=f"「{query}」の検索結果を回答の根拠に使いました。" if query else "",
        kind="search",
        badge=f"{len(source_items)}件",
        sources=result,
    )
    return _render_step(step, source_items)


def _summary_detail(steps: Sequence[TraceStep], source_total: int) -> str:
    # 折りたたみ時にも中身が想像できる1行サマリ
    # A one-line summary that hints at the content while collapsed.
    search_count = sum(1 for step in steps if step.kind in {"search", "reuse"})
    read_count = sum(1 for step in steps if step.kind == "read")
    follow_count = sum(1 for step in steps if step.kind == "follow")
    knowledge_count = sum(1 for step in steps if step.kind == "knowledge")
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
    if prompt_count:
        parts.append("共有プロンプト検索あり")
    return " · ".join(parts)


def _unique_source_total(
    rendered_steps: Sequence[tuple[TraceStep, list[str]]],
    fallback_result: WebSearchResult | None,
    fallback_items: Sequence[str],
) -> int:
    # 同じソースが複数ステップの一覧に出るため、URLで重複を除いて数える
    # The same source appears under several steps, so count distinct URLs.
    urls: set[str] = set()
    results = [step.sources for step, source_items in rendered_steps if source_items]
    if fallback_items:
        results.append(fallback_result)
    for result in results:
        if result is None:
            continue
        for source in result.sources:
            url = source.url.strip()
            if url:
                urls.add(url)
    return len(urls)


def build_web_search_trace_markdown(
    result: WebSearchResult | None = None,
    *,
    steps: Sequence[Any] | None = None,
) -> str:
    # 回答生成プロセスのトレースと検索ソースを表示するMarkdown/HTMLを構築する
    # Build markdown/HTML to display the response generation process trace and search sources.
    normalized_steps = [
        coerced for coerced in (_coerce_step(step) for step in steps or []) if coerced is not None
    ]
    fallback_items = (
        build_web_search_source_items(result)
        if result is not None and not any(step.sources is not None for step in normalized_steps)
        else []
    )
    if not normalized_steps and not fallback_items:
        return ""

    rendered_steps = [(step, build_web_search_source_items(step.sources)) for step in normalized_steps]
    step_html = [_render_step(step, source_items) for step, source_items in rendered_steps]
    if fallback_items:
        step_html.append(_render_fallback_source_step(result, fallback_items))

    source_total = _unique_source_total(rendered_steps, result, fallback_items)
    summary_detail = _summary_detail(normalized_steps, source_total)
    # Markdown上でHTMLブロックが途切れないよう、空行になる要素は差し込まない。
    # Never emit an empty line: a blank line would end the HTML block in Markdown.
    summary_detail_html = (
        [f'<span class="web-search-sources__summary-detail">{escape(summary_detail)}</span>']
        if summary_detail
        else []
    )

    return "\n".join(
        [
            '<details class="web-search-sources web-search-sources--trace">',
            '<summary class="web-search-sources__summary">',
            '<span class="web-search-sources__summary-main">',
            '<span class="web-search-sources__summary-icon"><i class="bi bi-list-check"></i></span>',
            '<span class="web-search-sources__summary-text">',
            '<span class="web-search-sources__label">回答までのステップ</span>',
            *summary_detail_html,
            "</span>",
            "</span>",
            f'<span class="web-search-sources__count">{len(step_html)}ステップ</span>',
            '<span class="web-search-sources__chevron"><i class="bi bi-chevron-down"></i></span>',
            "</summary>",
            '<div class="web-search-sources__list">',
            '<ol class="web-search-sources__steps">',
            *step_html,
            "</ol>",
            "</div>",
            "</details>",
        ]
    )
