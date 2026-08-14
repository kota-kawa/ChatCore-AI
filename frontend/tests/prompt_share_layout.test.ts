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
      onToggleLike: noop,
      onOpenAuthorProfile: noop
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
      onToggleLike: noop,
      onOpenAuthorProfile: noop
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
        ai_model: "Claude Haiku 4.5",
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
      onClose: noop,
      onOpenAuthorProfile: noop
    })
  );

  assert.match(html, /プロンプト本文/);
  // 本文はMarkdownとしてクライアント側でマウント後に描画されるため、
  // 静的マークアップの時点ではMarkdown用コンテナが選ばれていることだけを確認する
  // The body renders as Markdown only after client-side mount, so the static
  // markup only confirms the Markdown container was chosen for this content
  assert.match(html, /class="prompt-detail-markdown md-content"/);
  // カテゴリキーが表示ラベルへ解決されることを検証する
  // The category key must be resolved to its display label
  assert.match(html, /仕事・ビジネス/);
  assert.match(html, /Claude Haiku 4.5/);
  assert.match(html, /コピー/);
});

// 設定画面の閲覧モーダルと同じ枠組み（見出しブロック・入出力例パネル）を保つ
// The shell must keep the settings-page preview modal's frame: heading block, examples panel
test("prompt share detail modal keeps the settings-style shell", () => {
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
        content: "議事録を要約してください。",
        category: "business",
        author: "Kota",
        content_format: "prompt",
        media_type: "text",
        prompt_type: "text",
        input_examples: "長い会議メモ",
        output_examples: "要点 / 決定事項 / 次のアクション",
        liked: false,
        used_in_chat: false,
        comment_count: 0,
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
      onClose: noop,
      onOpenAuthorProfile: noop
    })
  );

  // 閉じる操作は他のモーダルと同じ丸ボタン1つだけ。冗長なフッターの「閉じる」は持たない
  // Closing is reachable only from the same round button the other modals use; no footer close
  assert.match(html, /<button type="button" class="close-btn" id="closePromptDetailModal"/);
  assert.doesNotMatch(html, /prompt-detail-close/);
  assert.doesNotMatch(html, /prompt-detail-footer/);
  // ヘッダーは上に固定せず、本文と同じスクロール領域の中に置く
  // The header is not pinned: it lives inside the same scroller as the body
  assert.ok(html.indexOf("prompt-detail-scroll") < html.indexOf("prompt-detail-header"));
  // 入出力例は1枚のパネルにまとめ、中を2枚のカードに割る
  // The examples share one panel that holds two cards
  assert.match(html, /prompt-detail-examples__grid/);
  assert.equal(html.match(/class="prompt-detail-example"/g)?.length, 2);
  assert.ok(html.indexOf("入出力例") < html.indexOf("prompt-detail-examples__grid"));
});

// SNSのように投稿者のアバターをボタン化し、プロフィールモーダルへ遷移できることを検証する
// Verifies the SNS-style author avatar renders as a button that links to the profile modal
test("prompt share detail modal renders a clickable author byline when a user ID is present", () => {
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
        content: "議事録を要約してください。",
        category: "business",
        author: "Kota",
        author_user_id: 42,
        author_avatar_url: "/static/uploads/avatar-42.png",
        content_format: "prompt",
        media_type: "text",
        prompt_type: "text",
        liked: false,
        used_in_chat: false,
        comment_count: 0,
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
      onClose: noop,
      onOpenAuthorProfile: noop
    })
  );

  assert.match(html, /<button type="button" class="prompt-detail-author"/);
  assert.match(html, /\/static\/uploads\/avatar-42\.png/);

  const withoutUserId = renderToStaticMarkup(
    React.createElement(PromptShareDetailModal, {
      isOpen: true,
      isLoggedIn: true,
      activeView: "detail",
      promptDetailModalRef: React.createRef<HTMLDivElement>(),
      commentsSectionRef: React.createRef<HTMLElement>(),
      commentTextareaRef: React.createRef<HTMLTextAreaElement>(),
      detailPrompt: {
        id: 13,
        clientId: "prompt-13",
        title: "会議メモ要約2",
        content: "議事録を要約してください。",
        category: "business",
        author: "Kota",
        content_format: "prompt",
        media_type: "text",
        prompt_type: "text",
        liked: false,
        used_in_chat: false,
        comment_count: 0,
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
      onClose: noop,
      onOpenAuthorProfile: noop
    })
  );

  // 投稿者IDが無い場合はボタン化せず、静的な署名として表示する
  // Without a user ID, the byline stays a static (non-button) element
  assert.doesNotMatch(withoutUserId, /<button type="button" class="prompt-detail-author"/);
  assert.match(withoutUserId, /class="prompt-detail-author prompt-detail-author--static"/);
});
