import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

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
      hasMoreSearchResults: false,
      isLoadingMoreSearchResults: false,
      onLoadMoreSearchResults: noop,
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
});
