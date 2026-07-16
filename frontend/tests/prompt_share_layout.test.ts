import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { PromptShareDetailModal } from "../components/prompt_share/prompt_share_detail_modal";
import { PromptSharePageLayout } from "../components/prompt_share/prompt_share_page_layout";

const noop = () => {};

test("prompt share layout renders crawlable page content before client API data loads", () => {
  const html = renderToStaticMarkup(
    React.createElement(PromptSharePageLayout, {
      authUiReady: true,
      isLoggedIn: false,
      searchInput: "",
      onSearchInputChange: noop,
      onSearchInputKeyDown: noop,
      onSearch: noop,
      onOpenComposerModal: noop,
      categories: [
        { value: "writing", label: "文章作成", iconClass: "bi bi-pencil" },
        { value: "research", label: "調査", iconClass: "bi bi-search" }
      ],
      selectedCategory: "all",
      onCategoryClick: noop,
      contentFormatFilters: [],
      selectedContentFormatFilter: "all",
      onContentFormatFilterClick: noop,
      mediaTypeFilters: [],
      selectedMediaTypeFilter: "all",
      onMediaTypeFilterClick: noop,
      selectedCategoryTitle: "全てのプロンプト",
      promptCountMeta: "公開プロンプトを読み込み中...",
      hasMoreResults: false,
      isLoadingMoreResults: false,
      onLoadMoreResults: noop,
      isPromptsLoading: true,
      hasPromptFeedback: false,
      visiblePrompts: [],
      feedbackToShow: null,
      openDropdownPromptId: null,
      likePendingIds: new Set<string>(),
      actionEffectIds: new Set<string>(),
      addAsTaskPendingIds: new Set<string>(),
      onOpenDetail: noop,
      onOpenComments: noop,
      onOpenShare: noop,
      onToggleDropdown: noop,
      onCloseDropdown: noop,
      onAddAsTask: noop,
      onToggleLike: noop
    })
  );

  assert.match(html, /公開プロンプトライブラリ/);
  assert.match(html, /Chat Coreのプロンプト共有/);
  assert.match(html, /文章作成/);
  assert.match(html, /調査/);
  assert.match(html, /title="文章作成"/);
});

test("prompt share layout places load more after the final prompt card", () => {
  const html = renderToStaticMarkup(
    React.createElement(PromptSharePageLayout, {
      authUiReady: true,
      isLoggedIn: true,
      searchInput: "",
      onSearchInputChange: noop,
      onSearchInputKeyDown: noop,
      onSearch: noop,
      onOpenComposerModal: noop,
      categories: [],
      selectedCategory: "all",
      onCategoryClick: noop,
      contentFormatFilters: [],
      selectedContentFormatFilter: "all",
      onContentFormatFilterClick: noop,
      mediaTypeFilters: [],
      selectedMediaTypeFilter: "all",
      onMediaTypeFilterClick: noop,
      selectedCategoryTitle: "全てのプロンプト",
      promptCountMeta: "公開プロンプト: 1件を表示",
      hasMoreResults: true,
      isLoadingMoreResults: false,
      onLoadMoreResults: noop,
      isPromptsLoading: false,
      hasPromptFeedback: false,
      visiblePrompts: [{
        id: 1,
        clientId: "prompt-1",
        title: "メール作成",
        content: "メール本文を作成してください。",
        content_format: "prompt",
        media_type: "text",
        liked: false,
        used_in_chat: false
      }],
      feedbackToShow: null,
      openDropdownPromptId: null,
      likePendingIds: new Set<string>(),
      actionEffectIds: new Set<string>(),
      addAsTaskPendingIds: new Set<string>(),
      onOpenDetail: noop,
      onOpenComments: noop,
      onOpenShare: noop,
      onToggleDropdown: noop,
      onCloseDropdown: noop,
      onAddAsTask: noop,
      onToggleLike: noop
    })
  );

  assert.ok(html.indexOf("prompt-card") < html.indexOf("prompt-load-more-container"));
  assert.match(html, /さらに読み込む/);
});

test("prompt share detail modal highlights prompt content and metadata", () => {
  const html = renderToStaticMarkup(
    React.createElement(PromptShareDetailModal, {
      isOpen: true,
      isLoggedIn: true,
      activeView: "detail",
      promptDetailModalRef: React.createRef<HTMLDivElement>(),
      commentsSectionRef: React.createRef<HTMLElement>(),
      commentTextareaRef: React.createRef<HTMLTextAreaElement>(),
      detailPrompt: {
        id: 12,
        clientId: "prompt-12",
        title: "会議メモ要約",
        content: "議事録を要点、決定事項、次のアクションに分けて要約してください。",
        category: "business",
        author: "Kota",
        content_format: "prompt",
        media_type: "text",
        prompt_type: "text",
        ai_model: "Gemini 2.5",
        input_examples: "長い会議メモ",
        output_examples: "要点 / 決定事項 / 次のアクション",
        liked: false,
        used_in_chat: false,
        comment_count: 3,
        created_at: "2026-06-01T00:00:00Z"
      },
      detailComments: [],
      isDetailCommentsLoading: false,
      isCommentSubmitting: false,
      commentDraft: "",
      commentActionPendingIds: new Set<string>(),
      promptDetailCloseButtonRef: React.createRef<HTMLButtonElement>(),
      onActiveViewChange: noop,
      onCommentDraftChange: noop,
      onSubmitComment: noop,
      onDeleteComment: noop,
      onReportComment: noop,
      onReloadComments: noop,
      onClose: noop
    })
  );

  assert.match(html, /プロンプト本文/);
  assert.match(html, /議事録を要点、決定事項、次のアクションに分けて要約してください。/);
  // カテゴリキーが表示ラベルへ解決されることを検証する
  // The category key must be resolved to its display label
  assert.match(html, /仕事・ビジネス/);
  assert.match(html, /Gemini 2.5/);
  assert.match(html, /コピー/);
});
