import React, { type KeyboardEvent as ReactKeyboardEvent, type MouseEvent, type ReactNode } from "react";

import { PromptCard, type PromptRecord } from "./prompt_card";
import type { PromptCategory, PromptFeedback, PromptTypeFilter, PromptTypeFilterOption } from "./prompt_share_page_types";

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
  promptTypeFilters: PromptTypeFilterOption[];
  selectedPromptTypeFilter: PromptTypeFilter;
  onPromptTypeFilterClick: (promptTypeFilter: PromptTypeFilter) => void;
  selectedCategoryTitle: string;
  promptCountMeta: string;
  hasMoreSearchResults: boolean;
  isLoadingMoreSearchResults: boolean;
  onLoadMoreSearchResults: () => void;
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
  promptTypeFilters,
  selectedPromptTypeFilter,
  onPromptTypeFilterClick,
  selectedCategoryTitle,
  promptCountMeta,
  hasMoreSearchResults,
  isLoadingMoreSearchResults,
  onLoadMoreSearchResults,
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
          className="auth-btn"
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
              className="hero-action hero-action--primary"
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
            Chat Coreのプロンプト共有では、文章作成、調査、画像生成、SKILLなどの日本語AIプロンプトをカテゴリ別に探せます。
            気になるプロンプトは詳細を確認し、コメントや共有リンクから使い方の文脈も追えます。
          </p>
          <ul>
            {categories.slice(0, 6).map((category) => (
              <li key={category.value}>{category.label}</li>
            ))}
          </ul>
        </section>

        {/* カテゴリフィルターとプロンプトタイプフィルターを並べたサイドバー的セクション */}
        {/* Category and type filter controls for narrowing down the prompt list */}
        <section className="categories" aria-labelledby="categories-title">
          <div className="section-header section-header--compact">
            <h2 id="categories-title">カテゴリ</h2>
          </div>

          <div className="category-list">
            {categories.map((category) => (
              <button
                key={category.value}
                type="button"
                className={`category-card${selectedCategory === category.value ? " active" : ""}`}
                data-category={category.value}
                onClick={() => {
                  onCategoryClick(category.value);
                }}
              >
                <i className={category.iconClass}></i>
                <span>{category.label}</span>
              </button>
            ))}
          </div>

          {/* タイプフィルターはrole="group"でカテゴリとは独立したコントロールグループにする */}
          {/* Type filters use role="group" to form a distinct ARIA group from category buttons */}
          <div className="prompt-filter-block">
            <div id="prompt-type-filter-title" className="prompt-filter-heading">
              表示タイプ
            </div>
            <div className="prompt-type-filter-list" role="group" aria-labelledby="prompt-type-filter-title">
              {promptTypeFilters.map((promptTypeFilter) => (
                <button
                  key={promptTypeFilter.value}
                  type="button"
                  className={`prompt-type-filter-btn${selectedPromptTypeFilter === promptTypeFilter.value ? " active" : ""}`}
                  aria-pressed={selectedPromptTypeFilter === promptTypeFilter.value ? "true" : "false"}
                  onClick={() => {
                    onPromptTypeFilterClick(promptTypeFilter.value);
                  }}
                >
                  <i className={promptTypeFilter.iconClass}></i>
                  <span>{promptTypeFilter.label}</span>
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
            {/* 追加ページが存在する場合のみ「さらに読み込む」ボタンを表示する */}
            {/* Show "load more" only when the API indicates more pages exist */}
            {hasMoreSearchResults ? (
              <button
                type="button"
                className="prompt-load-more"
                onClick={onLoadMoreSearchResults}
                disabled={isLoadingMoreSearchResults}
              >
                {isLoadingMoreSearchResults ? "読み込み中..." : "さらに読み込む"}
              </button>
            ) : null}
          </div>

          {/* 非React（レガシー）スクリプトのマウントポイント */}
          {/* Mount point for legacy non-React rendering scripts */}
          <div id="promptResults"></div>

          <div className="prompt-cards">
            {/* 初回ロード中のみローディングメッセージを表示し、フィードバックと重複させない */}
            {/* Show loading message only on initial empty load, not when feedback is displayed */}
            {isPromptsLoading && visiblePrompts.length === 0 && !hasPromptFeedback ? (
              <p className="prompt-loading-message">読み込み中...</p>
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
        </section>
      </main>

      {/* モーダルなど子コンポーネントをページ末尾に差し込む */}
      {/* Render child components (e.g. modals) at the end of the page */}
      {children}
    </div>
  );
}
