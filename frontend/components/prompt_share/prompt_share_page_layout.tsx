import React, { type KeyboardEvent as ReactKeyboardEvent, type MouseEvent, type ReactNode } from "react";

import { Skeleton, SkeletonText } from "../ui/skeleton";
import { PromptCard, type PromptRecord } from "./prompt_card";
import type {
  ContentFormatFilter,
  MediaTypeFilter,
  PromptAxisFilterOption,
  PromptCategory,
  PromptFeedback
} from "./prompt_share_page_types";

// ページ全体のレイアウトが受け取るすべての状態・フィルター・ハンドラを定義する
// Defines all state, filters, and event handlers passed into the page layout component
type PromptSharePageLayoutProps = {
  authUiReady: boolean;
  isLoggedIn: boolean;
  searchInput: string;
  onSearchInputChange: (value: string) => void;
  onSearchInputKeyDown: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
  onSearch: () => void;
  onOpenComposerModal: () => void;
  categories: PromptCategory[];
  selectedCategory: string;
  onCategoryClick: (category: string) => void;
  contentFormatFilters: PromptAxisFilterOption<ContentFormatFilter>[];
  selectedContentFormatFilter: ContentFormatFilter;
  onContentFormatFilterClick: (contentFormatFilter: ContentFormatFilter) => void;
  mediaTypeFilters: PromptAxisFilterOption<MediaTypeFilter>[];
  selectedMediaTypeFilter: MediaTypeFilter;
  onMediaTypeFilterClick: (mediaTypeFilter: MediaTypeFilter) => void;
  selectedCategoryTitle: string;
  promptCountMeta: string;
  hasMoreResults: boolean;
  isLoadingMoreResults: boolean;
  onLoadMoreResults: () => void;
  isPromptsLoading: boolean;
  hasPromptFeedback: boolean;
  visiblePrompts: PromptRecord[];
  feedbackToShow: PromptFeedback | null;
  openDropdownPromptId: string | null;
  likePendingIds: Set<string>;
  actionEffectIds: Set<string>;
  addAsTaskPendingIds: Set<string>;
  onOpenDetail: (prompt: PromptRecord) => void;
  onOpenComments: (prompt: PromptRecord) => void;
  onOpenShare: (prompt: PromptRecord, event?: Event | MouseEvent<HTMLButtonElement>) => void;
  onToggleDropdown: (promptId: string) => void;
  onCloseDropdown: () => void;
  onAddAsTask: (prompt: PromptRecord) => void;
  onToggleLike: (prompt: PromptRecord) => void;
  // モーダルなど追加UIを差し込める拡張スロット
  // Slot for injecting additional UI elements such as modals
  children?: ReactNode;
};

function PromptCardSkeletonGrid() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="prompt-card prompt-card--skeleton" role="status" aria-label="プロンプトを読み込み中">
          <div className="prompt-card__header">
            <div className="prompt-card__badges">
              <Skeleton variant="text" width={82} height="1.45rem" />
              <Skeleton variant="text" width={104} height="1.45rem" />
            </div>
            <Skeleton variant="circle" width={32} height={32} />
          </div>
          <Skeleton variant="text" width={index % 2 === 0 ? "70%" : "84%"} height="1.25rem" />
          <SkeletonText lines={3} />
          <div className="prompt-meta">
            <div className="prompt-actions">
              <Skeleton variant="circle" width={34} height={34} />
              <Skeleton variant="circle" width={34} height={34} />
              <Skeleton variant="circle" width={34} height={34} />
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

// プロンプト共有ページのヘッダー・フィルター・カード一覧を担う純粋なレイアウトコンポーネント
// Pure layout component for the prompt share page: header, filters, and card grid
export function PromptSharePageLayout({
  authUiReady,
  isLoggedIn,
  searchInput,
  onSearchInputChange,
  onSearchInputKeyDown,
  onSearch,
  onOpenComposerModal,
  categories,
  selectedCategory,
  onCategoryClick,
  contentFormatFilters,
  selectedContentFormatFilter,
  onContentFormatFilterClick,
  mediaTypeFilters,
  selectedMediaTypeFilter,
  onMediaTypeFilterClick,
  selectedCategoryTitle,
  promptCountMeta,
  hasMoreResults,
  isLoadingMoreResults,
  onLoadMoreResults,
  isPromptsLoading,
  hasPromptFeedback,
  visiblePrompts,
  feedbackToShow,
  openDropdownPromptId,
  likePendingIds,
  actionEffectIds,
  addAsTaskPendingIds,
  onOpenDetail,
  onOpenComments,
  onOpenShare,
  onToggleDropdown,
  onCloseDropdown,
  onAddAsTask,
  onToggleLike,
  children
}: PromptSharePageLayoutProps) {
  return (
    <div className="prompt-share-page cc-page-rise">
      {/* カスタム要素：グローバルなアクションメニューWebComponent */}
      {/* Custom element: global action menu Web Component */}
      <action-menu></action-menu>

      {/* 認証UIの準備ができており未ログインの場合のみログインボタンを表示する */}
      {/* Show login button only when auth is ready and the user is not logged in */}
      <div
        id="auth-buttons"
        style={{
          display: authUiReady && !isLoggedIn ? "" : "none",
          position: "fixed",
          top: 10,
          right: 10,
          zIndex: "var(--z-floating-controls)"
        }}
      >
        <button
          id="login-btn"
          className="auth-btn cc-press"
          type="button"
          onClick={() => {
            window.location.href = "/login";
          }}
        >
          <i className="bi bi-person-circle"></i>
          <span>ログイン / 登録</span>
        </button>
      </div>

      {/* ログイン済みのときだけユーザーアイコンWebComponentを表示する */}
      {/* User icon Web Component is hidden until auth is confirmed */}
      <user-icon id="userIcon" style={authUiReady && isLoggedIn ? undefined : { display: "none" }}></user-icon>

      <header className="prompts-header" aria-labelledby="promptShareHeroTitle">
        <div className="prompts-header__inner">
          <p className="hero-kicker">Prompt Share</p>
          <h1 id="promptShareHeroTitle" className="hero-title">
            必要なプロンプトを、すぐ検索。
          </h1>
          <p className="hero-description">
            シンプルな検索で公開プロンプトを見つけて、そのまま保存・共有できます。
          </p>

          {/* role="search"でランドマークとして検索UIをスクリーンリーダーに認識させる */}
          {/* role="search" exposes the search region as a landmark for screen readers */}
          <div className="search-section" role="search" aria-label="プロンプト検索">
            <div className="search-box">
              <input
                type="text"
                id="searchInput"
                data-agent-id="prompt.search-input"
                placeholder="キーワードでプロンプトを検索..."
                value={searchInput}
                onChange={(event) => {
                  onSearchInputChange(event.target.value);
                }}
                onKeyDown={onSearchInputKeyDown}
              />
              <button
                id="searchButton"
                type="button"
                className="cc-press"
                data-agent-id="prompt.search-button"
                aria-label="検索を実行する"
                data-tooltip="入力したキーワードで検索"
                data-tooltip-placement="bottom"
                onClick={onSearch}
              >
                <i className="bi bi-search"></i>
              </button>
            </div>
          </div>

          <div className="hero-actions">
            <button
              type="button"
              id="heroOpenPostModal"
              data-agent-id="prompt.open-composer"
              className="hero-action hero-action--primary cc-press"
              onClick={onOpenComposerModal}
            >
              <i className="bi bi-plus-lg"></i>
              <span>プロンプトを投稿</span>
            </button>
          </div>
        </div>
      </header>

      <main>
        {/* SEO用のサマリーセクション。カテゴリ一覧をリストとしてマークアップする */}
        {/* SEO summary section; lists categories as semantic markup for crawlers */}
        <section className="prompt-crawl-summary" aria-labelledby="prompt-crawl-summary-title">
          <h2 id="prompt-crawl-summary-title">公開プロンプトライブラリ</h2>
          <p>
            Chat Coreのプロンプト共有では、文章作成、調査、画像生成、SKILLなどの日本語AIプロンプトをカテゴリや形式別に探せます。
            気になるプロンプトは詳細を確認し、コメントや共有リンクから使い方の文脈も追えます。
          </p>
          <ul>
            {categories.slice(0, 6).map((category) => (
              <li key={category.value}>{category.label}</li>
            ))}
          </ul>
        </section>

        {/* カテゴリフィルターと2軸フィルターを並べたサイドバー的セクション */}
        {/* Category and two-axis filter controls for narrowing down the prompt list */}
        <section className="categories" aria-labelledby="categories-title">
          <div className="section-header section-header--compact">
            <h2 id="categories-title">カテゴリ</h2>
          </div>

          <div className="category-list">
            {categories.map((category) => (
              <button
                key={category.value}
                type="button"
                className={`category-card cc-press${selectedCategory === category.value ? " active" : ""}`}
                data-category={category.value}
                title={category.label}
                onClick={() => {
                  onCategoryClick(category.value);
                }}
              >
                <i className={category.iconClass}></i>
                <span>{category.label}</span>
              </button>
            ))}
          </div>

          {/* フォーマットフィルターはrole="group"でカテゴリとは独立したコントロールグループにする */}
          {/* Content format filters use role="group" to form a distinct ARIA group from category buttons */}
          <div className="prompt-filter-block">
            <div id="prompt-format-filter-title" className="prompt-filter-heading">
              フォーマット
            </div>
            <div className="prompt-type-filter-list" role="group" aria-labelledby="prompt-format-filter-title">
              {contentFormatFilters.map((contentFormatFilter) => (
                <button
                  key={contentFormatFilter.value}
                  type="button"
                  className={`prompt-type-filter-btn cc-press${selectedContentFormatFilter === contentFormatFilter.value ? " active" : ""}`}
                  aria-pressed={selectedContentFormatFilter === contentFormatFilter.value ? "true" : "false"}
                  onClick={() => {
                    onContentFormatFilterClick(contentFormatFilter.value);
                  }}
                >
                  <i className={contentFormatFilter.iconClass}></i>
                  <span>{contentFormatFilter.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* メディアフィルターはフォーマットとは独立し、画像・動画などの生成対象で絞り込む */}
          {/* Media filters are independent from format filters and narrow by generation target */}
          <div className="prompt-filter-block">
            <div id="prompt-media-filter-title" className="prompt-filter-heading">
              生成メディア
            </div>
            <div className="prompt-type-filter-list" role="group" aria-labelledby="prompt-media-filter-title">
              {mediaTypeFilters.map((mediaTypeFilter) => (
                <button
                  key={mediaTypeFilter.value}
                  type="button"
                  className={`prompt-type-filter-btn cc-press${selectedMediaTypeFilter === mediaTypeFilter.value ? " active" : ""}`}
                  aria-pressed={selectedMediaTypeFilter === mediaTypeFilter.value ? "true" : "false"}
                  onClick={() => {
                    onMediaTypeFilterClick(mediaTypeFilter.value);
                  }}
                >
                  <i className={mediaTypeFilter.iconClass}></i>
                  <span>{mediaTypeFilter.label}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* プロンプトカード一覧セクション */}
        {/* Prompt card feed section */}
        <section id="prompt-feed-section" data-agent-id="prompt.results" className="prompts-list" aria-labelledby="selected-category-title">
          <div className="section-header prompts-list-header section-header--compact">
            <h2 id="selected-category-title">{selectedCategoryTitle}</h2>
          </div>

          <div className="prompt-toolbar">
            <p id="promptCountMeta" className="prompt-count-meta">
              {promptCountMeta}
            </p>
          </div>

          {/* 非React（レガシー）スクリプトのマウントポイント */}
          {/* Mount point for legacy non-React rendering scripts */}
          <div id="promptResults"></div>

          <div className="prompt-cards">
            {/* 初回ロード中のみローディングメッセージを表示し、フィードバックと重複させない */}
            {/* Show loading message only on initial empty load, not when feedback is displayed */}
            {isPromptsLoading && visiblePrompts.length === 0 && !hasPromptFeedback ? (
              <PromptCardSkeletonGrid />
            ) : null}

            {/* エラーや空状態のフィードバックをvariantに応じたスタイルで表示する */}
            {/* Show feedback message with variant-specific styling for error or empty states */}
            {feedbackToShow ? (
              <p className={`prompt-feedback prompt-feedback--${feedbackToShow.variant}`}>
                {feedbackToShow.message}
              </p>
            ) : null}

            {visiblePrompts.map((prompt) => {
              const promptId = prompt.clientId;
              return (
                // 各カードに必要な状態とハンドラをSetから引いて渡す
                // Look up per-card state from Sets and forward the right handlers
                <PromptCard
                  key={promptId}
                  prompt={prompt}
                  isDropdownOpen={openDropdownPromptId === promptId}
                  isLikePending={likePendingIds.has(promptId)}
                  isLikeEffectActive={actionEffectIds.has(`${promptId}:like`)}
                  isAddAsTaskPending={addAsTaskPendingIds.has(promptId)}
                  isUseInChatEffectActive={actionEffectIds.has(`${promptId}:use-in-chat`)}
                  onOpenDetail={onOpenDetail}
                  onOpenComments={onOpenComments}
                  onOpenShare={onOpenShare}
                  onToggleDropdown={onToggleDropdown}
                  onCloseDropdown={onCloseDropdown}
                  onAddAsTask={onAddAsTask}
                  onToggleLike={onToggleLike}
                />
              );
            })}
          </div>

          {/* 読了後の次の操作として、追加読み込みはカード一覧の末尾に表示する */}
          {/* Put the next action after the last card, where readers naturally reach it */}
          {hasMoreResults ? (
            <div className="prompt-load-more-container">
              <button
                type="button"
                className="prompt-load-more cc-press"
                onClick={onLoadMoreResults}
                disabled={isLoadingMoreResults}
              >
                {isLoadingMoreResults ? "読み込み中..." : "さらに読み込む"}
              </button>
            </div>
          ) : null}
        </section>
      </main>

      {/* モーダルなど子コンポーネントをページ末尾に差し込む */}
      {/* Render child components (e.g. modals) at the end of the page */}
      {children}
    </div>
  );
}
