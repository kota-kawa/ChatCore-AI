import { type KeyboardEvent as ReactKeyboardEvent, type MouseEvent, type ReactNode } from "react";

import { PromptCard, type PromptRecord } from "./prompt_card";
import type { PromptCategory, PromptFeedback } from "./prompt_share_page_types";

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
  bookmarkPendingIds: Set<string>;
  saveToListPendingIds: Set<string>;
  onOpenDetail: (prompt: PromptRecord) => void;
  onOpenShare: (prompt: PromptRecord, event?: Event | MouseEvent<HTMLButtonElement>) => void;
  onToggleDropdown: (promptId: string) => void;
  onCloseDropdown: () => void;
  onSaveToList: (prompt: PromptRecord) => void;
  onToggleLike: (prompt: PromptRecord) => void;
  onToggleBookmark: (prompt: PromptRecord) => void;
  children?: ReactNode;
};

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
  bookmarkPendingIds,
  saveToListPendingIds,
  onOpenDetail,
  onOpenShare,
  onToggleDropdown,
  onCloseDropdown,
  onSaveToList,
  onToggleLike,
  onToggleBookmark,
  children
}: PromptSharePageLayoutProps) {
  return (
    <div className="prompt-share-page">
      <action-menu></action-menu>

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

          <div className="search-section" role="search" aria-label="プロンプト検索">
            <div className="search-box">
              <input
                type="text"
                id="searchInput"
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
        </section>

        <section id="prompt-feed-section" className="prompts-list" aria-labelledby="selected-category-title">
          <div className="section-header prompts-list-header section-header--compact">
            <h2 id="selected-category-title">{selectedCategoryTitle}</h2>
          </div>

          <div className="prompt-toolbar">
            <p id="promptCountMeta" className="prompt-count-meta">
              {promptCountMeta}
            </p>
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

          <div id="promptResults"></div>

          <div className="prompt-cards">
            {isPromptsLoading && visiblePrompts.length === 0 && !hasPromptFeedback ? (
              <p className="prompt-loading-message">読み込み中...</p>
            ) : null}

            {feedbackToShow ? (
              <p className={`prompt-feedback prompt-feedback--${feedbackToShow.variant}`}>
                {feedbackToShow.message}
              </p>
            ) : null}

            {visiblePrompts.map((prompt) => {
              const promptId = prompt.clientId;
              return (
                <PromptCard
                  key={promptId}
                  prompt={prompt}
                  isDropdownOpen={openDropdownPromptId === promptId}
                  isLikePending={likePendingIds.has(promptId)}
                  isBookmarkPending={bookmarkPendingIds.has(promptId)}
                  isSaveToListPending={saveToListPendingIds.has(promptId)}
                  onOpenDetail={onOpenDetail}
                  onOpenShare={onOpenShare}
                  onToggleDropdown={onToggleDropdown}
                  onCloseDropdown={onCloseDropdown}
                  onSaveToList={onSaveToList}
                  onToggleLike={onToggleLike}
                  onToggleBookmark={onToggleBookmark}
                />
              );
            })}
          </div>
        </section>
      </main>

      {children}
    </div>
  );
}
