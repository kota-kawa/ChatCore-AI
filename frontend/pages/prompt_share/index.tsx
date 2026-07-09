import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent
} from "react";

import { SeoHead } from "../../components/SeoHead";
import "../../scripts/core/csrf";
import { showToast } from "../../scripts/core/toast";
import { initPromptAssist } from "../../scripts/components/prompt_assist";
import {
  createPrompt,
  fetchPromptList,
  fetchPromptSearchResults
} from "../../scripts/prompt_share/api";
import { normalizePromptData } from "../../scripts/prompt_share/formatters";
import {
  buildAttributes,
  deriveLegacyPromptType,
  mediaAllowsAttachment
} from "../../scripts/prompt_share/prompt_type_registry";
import {
  readPromptCache,
  writePromptCache
} from "../../scripts/prompt_share/storage";
import type {
  ContentFormat,
  MediaType,
  PromptData,
  PromptPagination,
  PromptType
} from "../../scripts/prompt_share/types";
import { PromptShareComposerModal } from "../../components/prompt_share/prompt_share_composer_modal";
import { PromptShareDetailModal } from "../../components/prompt_share/prompt_share_detail_modal";
import {
  buildInitialPromptRecords,
  buildPromptCountMeta,
  filterPrompts,
  getFilterEmptyMessage,
  toCachedPromptData
} from "../../components/prompt_share/prompt_share_page_feed_utils";
import {
  PROMPT_CATEGORIES,
  PROMPT_CATEGORY_OPTIONS,
  PROMPT_CONTENT_FORMAT_FILTERS,
  PROMPT_MEDIA_TYPE_FILTERS,
  SEARCH_RESULTS_PER_PAGE
} from "../../components/prompt_share/prompt_share_page_constants";
import { CATEGORY_UNSET } from "../../scripts/prompt_share/prompt_category_registry";
import { PromptSharePageLayout } from "../../components/prompt_share/prompt_share_page_layout";
import type {
  ContentFormatFilter,
  MediaTypeFilter,
  PromptFeedback,
  PromptPostStatus,
  PromptPostStatusVariant
} from "../../components/prompt_share/prompt_share_page_types";
import {
  getCategoryTitle,
  getPromptId
} from "../../components/prompt_share/prompt_share_page_utils";
import { PromptShareShareModal } from "../../components/prompt_share/prompt_share_share_modal";
import type { PromptRecord } from "../../components/prompt_share/prompt_card";
import { usePromptImageSelection } from "../../components/prompt_share/use_prompt_image_selection";
import { usePromptCardActions } from "../../components/prompt_share/use_prompt_card_actions";
import { usePromptComments } from "../../components/prompt_share/use_prompt_comments";
import { usePromptModalManager } from "../../components/prompt_share/use_prompt_modal_manager";
import { usePromptShareActionEffects } from "../../components/prompt_share/use_prompt_share_action_effects";
import { usePromptShareAuth } from "../../components/prompt_share/use_prompt_share_auth";
import { usePromptShareDialog } from "../../components/prompt_share/use_prompt_share_dialog";
import { usePromptSharePageSetup } from "../../components/prompt_share/use_prompt_share_page_setup";
import {
  getPromptShareServerSideProps,
  promptShareDescription,
  promptShareStructuredData,
  type PromptSharePageProps
} from "../../components/prompt_share/prompt_share_page_data";

export const getServerSideProps = getPromptShareServerSideProps;

// プロンプト共有ページのメインコンポーネント。検索・フィルタ・モーダル・いいね・チャット追加など全機能を管理する
// Main component for the prompt share page; manages search, filters, modals, likes, use-in-chat, and all other features
export default function PromptSharePage({ initialPrompts = [] }: PromptSharePageProps) {
  // SSRで受け取った初期プロンプトをクライアント用レコード形式に変換する（マウント時のみ実行）
  // Transforms SSR-provided prompts into client records on mount only, avoiding unnecessary recomputation
  const initialPromptRecords = useMemo<PromptRecord[]>(() => {
    return buildInitialPromptRecords(initialPrompts);
  }, [initialPrompts]);

  const { authUiReady, isLoggedIn } = usePromptShareAuth();

  // 検索・フィルタ関連の状態
  // Search and filter state
  const [searchInput, setSearchInput] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [selectedCategoryTitle, setSelectedCategoryTitle] = useState("全てのプロンプト");
  const [appliedCategoryFilter, setAppliedCategoryFilter] = useState<string | null>("all");
  const [selectedContentFormatFilter, setSelectedContentFormatFilter] = useState<ContentFormatFilter>("all");
  const [selectedMediaTypeFilter, setSelectedMediaTypeFilter] = useState<MediaTypeFilter>("all");

  // プロンプト一覧の状態。SSRデータで初期化することで、初期描画をキャッシュで高速化する
  // Prompt list state; initialized from SSR data to speed up the first render with cached content
  const [prompts, setPrompts] = useState<PromptRecord[]>(initialPromptRecords);
  const [isPromptsLoading, setIsPromptsLoading] = useState(initialPromptRecords.length === 0);
  const [promptCountMeta, setPromptCountMeta] = useState(
    initialPromptRecords.length > 0
      ? `全てのプロンプト: ${initialPromptRecords.length}件`
      : "公開プロンプトを読み込み中..."
  );
  const [promptFeedback, setPromptFeedback] = useState<PromptFeedback | null>(null);
  const [activeSearchQuery, setActiveSearchQuery] = useState("");
  const [searchPagination, setSearchPagination] = useState<PromptPagination | null>(null);
  const [isLoadingMoreSearchResults, setIsLoadingMoreSearchResults] = useState(false);

  // モーダルの状態。どのモーダルが開いているかと、詳細・コメントビューの切り替えを管理する
  // Modal state: tracks which modal is open and toggles between detail and comments views
  const [detailModalView, setDetailModalView] = useState<"detail" | "comments">("detail");
  const [detailPrompt, setDetailPrompt] = useState<PromptRecord | null>(null);
  const {
    createPromptShareLink,
    handleCopyShareLink,
    handleNativeShare,
    shareActionLoading,
    shareSnsLinks,
    shareStatus,
    shareUrl
  } = usePromptShareDialog();

  // カードのドロップダウンとアクションの保留中IDを追跡する
  // Tracks open card dropdown and pending action IDs to prevent duplicate requests
  const [openDropdownPromptId, setOpenDropdownPromptId] = useState<string | null>(null);
  const { actionEffectIds, triggerActionEffect } = usePromptShareActionEffects();

  // 投稿フォームの各フィールドの状態
  // Composer form field states
  // 2軸モデル: フォーマット軸 × メディア軸。
  // Two-axis model: content format axis × media type axis.
  const [contentFormat, setContentFormat] = useState<ContentFormat>("prompt");
  const [mediaType, setMediaType] = useState<MediaType>("text");
  const [postTitle, setPostTitle] = useState("");
  // カテゴリは保存用の安定キーで保持する。空文字列は「未選択」を表す。
  // The category is held as the stable key persisted to the DB; empty means unselected.
  const [postCategory, setPostCategory] = useState(CATEGORY_UNSET);
  const [postContent, setPostContent] = useState("");
  const [postAiModel, setPostAiModel] = useState("");
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [postInputExample, setPostInputExample] = useState("");
  const [postOutputExample, setPostOutputExample] = useState("");
  const [postSkillMarkdown, setPostSkillMarkdown] = useState("");
  const [postSkillPythonScript, setPostSkillPythonScript] = useState("");
  const [isPostSubmitting, setIsPostSubmitting] = useState(false);
  const [promptPostStatus, setPromptPostStatusState] = useState<PromptPostStatus>({
    message: "",
    variant: "info"
  });

  // Refは非同期コールバックからも常に最新の状態値にアクセスするために使用する
  // Refs allow async callbacks to always read the latest state without stale closures
  const nextPromptClientIdRef = useRef(initialPromptRecords.length);
  const promptsRef = useRef<PromptRecord[]>(initialPromptRecords);
  const selectedCategoryRef = useRef("all");
  const selectedContentFormatFilterRef = useRef<ContentFormatFilter>("all");
  const selectedMediaTypeFilterRef = useRef<MediaTypeFilter>("all");
  // モーダルのDOM要素への参照。フォーカス管理とアクセシビリティのために使用する
  // Refs to modal DOM elements for focus management and accessibility
  const postModalRef = useRef<HTMLDivElement | null>(null);
  const promptDetailModalRef = useRef<HTMLDivElement | null>(null);
  const promptCommentsSectionRef = useRef<HTMLElement | null>(null);
  const promptCommentTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const promptShareModalRef = useRef<HTMLDivElement | null>(null);

  // 投稿フォームのフォーム要素への参照。バリデーションとAI補助機能の初期化に使用する
  // Refs to composer form elements used for validation and AI-assist initialization
  const promptPostTitleInputRef = useRef<HTMLInputElement | null>(null);
  const promptPostCategorySelectRef = useRef<HTMLSelectElement | null>(null);
  const promptPostContentTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const promptPostAiModelSelectRef = useRef<HTMLSelectElement | null>(null);
  const promptPostInputExamplesRef = useRef<HTMLTextAreaElement | null>(null);
  const promptPostOutputExamplesRef = useRef<HTMLTextAreaElement | null>(null);
  const promptPostSkillMarkdownRef = useRef<HTMLTextAreaElement | null>(null);
  const promptPostSkillPythonScriptRef = useRef<HTMLTextAreaElement | null>(null);

  const {
    clearPromptImageSelection,
    handleReferenceImageChange,
    promptImageInputRef,
    promptImagePreviewName,
    promptImagePreviewUrl,
    referenceImageFile,
    validateReferenceImageFile
  } = usePromptImageSelection(mediaType);

  // AI補助パネルの制御。一度だけ初期化し、プロンプトタイプ変更時に更新する
  // AI-assist panel control; initialized once and updated when prompt type changes
  const promptAssistRootRef = useRef<HTMLDivElement | null>(null);
  const promptAssistInitializedRef = useRef(false);
  const promptAssistControllerRef = useRef<{ reset: () => void; updateForPromptType: (t: string) => void } | null>(null);
  const promptTypeRef = useRef<PromptType>("text");

  const promptDetailCloseButtonRef = useRef<HTMLButtonElement | null>(null);
  const promptShareCopyButtonRef = useRef<HTMLButtonElement | null>(null);

  // 投稿後にモーダルを自動で閉じるタイマーの参照
  // Reference to the timer that auto-closes the composer modal after a successful post
  const postCloseTimerRef = useRef<number | null>(null);

  // stateが変わるたびにRefを同期する。これにより非同期コールバック内でも最新値を参照できる
  // Syncs refs whenever state changes so async callbacks always see the latest values
  useEffect(() => {
    promptsRef.current = prompts;
  }, [prompts]);

  useEffect(() => {
    selectedCategoryRef.current = selectedCategory;
  }, [selectedCategory]);

  useEffect(() => {
    selectedContentFormatFilterRef.current = selectedContentFormatFilter;
  }, [selectedContentFormatFilter]);

  useEffect(() => {
    selectedMediaTypeFilterRef.current = selectedMediaTypeFilter;
  }, [selectedMediaTypeFilter]);

  // AI補助やフィルタ文脈用に、2軸から派生した旧 prompt_type を最新に保つ。
  // Keep the legacy prompt_type (derived from the two axes) current for AI-assist/filter context.
  useEffect(() => {
    promptTypeRef.current = deriveLegacyPromptType(contentFormat, mediaType);
  }, [contentFormat, mediaType]);

  // 投稿ステータスメッセージをvariantとともに更新するためのヘルパー
  // Helper to update the post status message together with its severity variant
  const setPromptPostStatus = useCallback(
    (message: string, variant: PromptPostStatusVariant = "info") => {
      setPromptPostStatusState({ message, variant });
    },
    []
  );

  // エラー表示中のみクリアする。情報メッセージはユーザーが操作を続けても消さない
  // Clears the status only when it shows an error, so informational messages persist while the user edits
  const updatePromptFeedbackErrorIfNeeded = useCallback(() => {
    setPromptPostStatusState((current) => {
      if (current.variant !== "error") {
        return current;
      }
      return { message: "", variant: "info" };
    });
  }, []);

  // APIレスポンスのPromptDataをReactが管理するPromptRecordへ変換し、一意のclientIdを付与する
  // Converts API PromptData into React-managed PromptRecords with unique clientIds
  const toPromptRecords = useCallback((items: PromptData[]) => {
    return items.map((item) => ({
      ...normalizePromptData(item),
      clientId: `prompt-${++nextPromptClientIdRef.current}`,
      liked: Boolean(item.liked),
      used_in_chat: Boolean(item.used_in_chat)
    }));
  }, []);

  // カテゴリ・フォーマット・メディアでフィルタリングした後の表示対象プロンプト一覧
  // Derived list of prompts visible after applying category and two-axis filters
  const visiblePrompts = useMemo(() => {
    return filterPrompts(
      prompts,
      appliedCategoryFilter,
      selectedContentFormatFilter,
      selectedMediaTypeFilter
    );
  }, [
    filterPrompts,
    prompts,
    appliedCategoryFilter,
    selectedContentFormatFilter,
    selectedMediaTypeFilter
  ]);

  // 検索中かつ次ページが存在する場合に「もっと見る」ボタンを表示する
  // Indicates whether a "load more" button should be shown for search results
  const hasMoreSearchResults =
    activeSearchQuery.trim().length > 0 && Boolean(searchPagination?.has_next);

  // 投稿モーダルのステータスと送信中フラグをリセットし、AI補助パネルも初期状態へ戻す
  // Resets the post modal status, the submitting flag, and the AI-assist panel to their initial states
  const resetPostModalState = useCallback(() => {
    setPromptPostStatus("", "info");
    setIsPostSubmitting(false);
    promptAssistControllerRef.current?.reset();
  }, [setPromptPostStatus]);

  // 指定プロンプトのコメント数を一覧と詳細モーダルの両方で同期して更新する
  // Synchronously updates the comment count in both the prompt list and the detail modal
  const updatePromptCommentCount = useCallback(
    (promptId: string | number, nextCount: number) => {
      const normalizedPromptId = String(promptId);
      const safeCount = Math.max(0, Number(nextCount || 0));
      setPrompts((current) => {
        const next = current.map((prompt) =>
          String(prompt.id ?? "") === normalizedPromptId
            ? {
                ...prompt,
                comment_count: safeCount
              }
            : prompt
        );
        writePromptCache(toCachedPromptData(next));
        return next;
      });
      setDetailPrompt((current) => {
        if (!current || String(current.id ?? "") !== normalizedPromptId) {
          return current;
        }
        return {
          ...current,
          comment_count: safeCount
        };
      });
    },
    []
  );

  const {
    commentActionPendingIds,
    commentDraft,
    detailComments,
    handleDeletePromptComment,
    handleReportPromptComment,
    handleSubmitPromptComment,
    isCommentSubmitting,
    isDetailCommentsLoading,
    loadPromptComments,
    reloadDetailComments,
    resetPromptComments,
    setCommentDraft
  } = usePromptComments({
    detailPrompt,
    isLoggedIn,
    updatePromptCommentCount
  });

  const { activeModal, closeModal, hasModalLockRef, openModal } = usePromptModalManager({
    isPostSubmitting,
    onCloseDetail: () => {
      setDetailModalView("detail");
      setDetailPrompt(null);
      resetPromptComments();
    },
    onClosePost: resetPostModalState,
    postModalRef,
    promptDetailModalRef,
    promptShareModalRef
  });

  const supportsNativeShare = usePromptSharePageSetup({
    hasModalLockRef,
    postCloseTimerRef
  });

  // 単一のプロンプトレコードを更新し、変更後の一覧をローカルキャッシュに書き込む
  // Updates a single prompt record and writes the updated list to local cache
  const updatePromptRecord = useCallback(
    (clientId: string, updater: (prompt: PromptRecord) => PromptRecord) => {
      setPrompts((current) => {
        const next = current.map((prompt) => (prompt.clientId === clientId ? updater(prompt) : prompt));
        writePromptCache(toCachedPromptData(next));
        return next;
      });
      setDetailPrompt((current) => {
        if (!current || current.clientId !== clientId) {
          return current;
        }
        return updater(current);
      });
    },
    [toCachedPromptData]
  );

  // APIからプロンプト一覧を取得し、フィルタ状態を適用した上でキャッシュに書き込む
  // Fetches the full prompt list from the API, applies filter state, and writes the result to cache
  const loadPrompts = useCallback(
    async (options?: {
      categoryToApply?: string;
      contentFormatToApply?: ContentFormatFilter;
      mediaTypeToApply?: MediaTypeFilter;
    }) => {
      const categoryToApply = options?.categoryToApply || selectedCategoryRef.current;
      const contentFormatToApply =
        options?.contentFormatToApply || selectedContentFormatFilterRef.current;
      const mediaTypeToApply =
        options?.mediaTypeToApply || selectedMediaTypeFilterRef.current;
      if (promptsRef.current.length === 0) {
        setIsPromptsLoading(true);
      }

      try {
        const data = await fetchPromptList();
        const normalizedPrompts = Array.isArray(data.prompts)
          ? data.prompts.map(normalizePromptData)
          : [];

        writePromptCache(normalizedPrompts);
        const promptRecords = toPromptRecords(normalizedPrompts);

        setPrompts(promptRecords);
        setActiveSearchQuery("");
        setSearchPagination(null);
        setSelectedCategory(categoryToApply);
        setSelectedContentFormatFilter(contentFormatToApply);
        setSelectedMediaTypeFilter(mediaTypeToApply);
        setAppliedCategoryFilter(categoryToApply);
        setSelectedCategoryTitle(getCategoryTitle(categoryToApply));

        if (promptRecords.length > 0) {
          setPromptFeedback(null);
        } else {
          setPromptFeedback({
            message: "プロンプトが見つかりませんでした。",
            variant: "empty"
          });
        }

        setPromptCountMeta(
          buildPromptCountMeta(promptRecords, categoryToApply, contentFormatToApply, mediaTypeToApply)
        );
      } catch (error) {
        console.error("プロンプト取得エラー:", error);
        const message = error instanceof Error ? error.message : String(error);
        setPromptCountMeta("読み込みに失敗しました");
        setPromptFeedback({
          message: `エラーが発生しました: ${message}`,
          variant: "error"
        });
      } finally {
        setIsPromptsLoading(false);
      }
    },
    [buildPromptCountMeta, toPromptRecords]
  );

  // 入力文字列でプロンプトを検索し、クエリが空の場合は通常の一覧表示に戻る
  // Searches prompts by the current input; falls back to the full list if the query is empty
  const searchPrompts = useCallback(async (options?: {
    contentFormatToApply?: ContentFormatFilter;
    mediaTypeToApply?: MediaTypeFilter;
  }) => {
    const query = searchInput.trim();
    const contentFormatToApply =
      options?.contentFormatToApply || selectedContentFormatFilterRef.current;
    const mediaTypeToApply =
      options?.mediaTypeToApply || selectedMediaTypeFilterRef.current;

    if (!query) {
      setSelectedCategoryTitle("全てのプロンプト");
      await loadPrompts({ contentFormatToApply, mediaTypeToApply });
      return;
    }

    if (promptsRef.current.length === 0) {
      setIsPromptsLoading(true);
    }
    setSelectedCategoryTitle(`検索結果: 「${query}」`);

    try {
      const data = await fetchPromptSearchResults(query, {
        page: 1,
        perPage: SEARCH_RESULTS_PER_PAGE,
        contentFormat: contentFormatToApply,
        mediaType: mediaTypeToApply
      });
      const normalizedPrompts = Array.isArray(data.prompts)
        ? data.prompts.map(normalizePromptData)
        : [];
      const promptRecords = toPromptRecords(normalizedPrompts);

      setPrompts(promptRecords);
      setSelectedContentFormatFilter(contentFormatToApply);
      setSelectedMediaTypeFilter(mediaTypeToApply);
      setActiveSearchQuery(query);
      setSearchPagination(data.pagination || null);
      // 検索中はカテゴリフィルタを無効化する
      // Disable category filter while a search is active
      setAppliedCategoryFilter(null);

      if (promptRecords.length > 0) {
        setPromptFeedback(null);
      } else {
        setPromptFeedback({
          message: "該当するプロンプトが見つかりませんでした。",
          variant: "empty"
        });
      }
      setPromptCountMeta(
        buildPromptCountMeta(promptRecords, null, contentFormatToApply, mediaTypeToApply, {
          searchTotal: Number(data.pagination?.total || promptRecords.length)
        })
      );
    } catch (error) {
      console.error("検索エラー:", error);
      const message = error instanceof Error ? error.message : String(error);
      setPromptCountMeta("検索に失敗しました");
      setPromptFeedback({
        message: `エラーが発生しました: ${message}`,
        variant: "error"
      });
    } finally {
      setIsPromptsLoading(false);
    }
  }, [buildPromptCountMeta, loadPrompts, searchInput, toPromptRecords]);

  // 検索結果の次ページを取得して既存リストに追記する（無限スクロール的な追加読み込み）
  // Fetches the next page of search results and appends them to the existing list (infinite-scroll style)
  const loadMoreSearchResults = useCallback(async () => {
    const query = activeSearchQuery.trim();
    const nextPage = Number(searchPagination?.page || 0) + 1;
    if (!query || !searchPagination?.has_next || nextPage <= 1) {
      return;
    }

    setIsLoadingMoreSearchResults(true);
    try {
      const data = await fetchPromptSearchResults(query, {
        page: nextPage,
        perPage: Number(searchPagination.per_page || SEARCH_RESULTS_PER_PAGE),
        contentFormat: selectedContentFormatFilterRef.current,
        mediaType: selectedMediaTypeFilterRef.current
      });
      const normalizedPrompts = Array.isArray(data.prompts)
        ? data.prompts.map(normalizePromptData)
        : [];
      const promptRecords = toPromptRecords(normalizedPrompts);
      const nextPrompts = [...promptsRef.current, ...promptRecords];

      setPrompts(nextPrompts);
      setSearchPagination(data.pagination || null);
      setPromptFeedback(null);
      setPromptCountMeta(
        buildPromptCountMeta(
          nextPrompts,
          null,
          selectedContentFormatFilterRef.current,
          selectedMediaTypeFilterRef.current,
          {
            searchTotal: Number(data.pagination?.total || nextPrompts.length)
          }
        )
      );
    } catch (error) {
      console.error("追加検索エラー:", error);
      const message = error instanceof Error ? error.message : String(error);
      setPromptFeedback({
        message: `追加読み込みに失敗しました: ${message}`,
        variant: "error"
      });
    } finally {
      setIsLoadingMoreSearchResults(false);
    }
  }, [activeSearchQuery, buildPromptCountMeta, searchPagination, toPromptRecords]);

  // 共有モーダルを開き、対象プロンプトの共有URLを非同期で生成する
  // Opens the share modal and asynchronously generates the share URL for the target prompt
  const openPromptShareDialog = useCallback(
    (prompt: PromptRecord, event?: Event | MouseEvent<HTMLButtonElement>) => {
      event?.stopPropagation();
      setOpenDropdownPromptId(null);
      openModal("share", promptShareCopyButtonRef.current);
      void createPromptShareLink(prompt, false);
    },
    [createPromptShareLink, openModal]
  );

  // 詳細ビューでプロンプト詳細モーダルを開き、コメントを非同期で取得する
  // Opens the prompt detail modal in detail view and asynchronously fetches comments
  const openPromptDetailModal = useCallback(
    (prompt: PromptRecord) => {
      const promptId = getPromptId(prompt);
      setOpenDropdownPromptId(null);
      setDetailModalView("detail");
      setDetailPrompt(prompt);
      resetPromptComments();
      openModal("detail", promptDetailCloseButtonRef.current);
      if (promptId) {
        void loadPromptComments(promptId);
      }
    },
    [loadPromptComments, openModal, resetPromptComments]
  );

  // コメントビューで詳細モーダルを直接開き、テキストエリアへのフォーカスを優先する
  // Opens the detail modal directly in comments view, prioritizing focus on the textarea
  const openPromptCommentsModal = useCallback(
    (prompt: PromptRecord) => {
      const promptId = getPromptId(prompt);
      setOpenDropdownPromptId(null);
      setDetailModalView("comments");
      setDetailPrompt(prompt);
      resetPromptComments();
      openModal("detail", promptCommentTextareaRef.current || promptCommentsSectionRef.current);
      if (promptId) {
        void loadPromptComments(promptId);
      }
    },
    [loadPromptComments, openModal, resetPromptComments]
  );

  // 同じカードのドロップダウンを再度クリックした場合はトグルとして閉じる
  // Toggles the dropdown closed if the same card's menu is clicked again
  const togglePromptDropdown = useCallback((promptId: string) => {
    setOpenDropdownPromptId((current) => (current === promptId ? null : promptId));
  }, []);

  const closePromptDropdown = useCallback(() => {
    setOpenDropdownPromptId(null);
  }, []);

  const {
    addAsTaskPendingIds,
    handleAddPromptAsTask,
    handleTogglePromptLike,
    likePendingIds
  } = usePromptCardActions({
    closePromptDropdown,
    isLoggedIn,
    triggerActionEffect,
    updatePromptRecord
  });

  // 未ログイン時はトーストで案内し、ログイン済みの場合は投稿モーダルを開く
  // Shows a toast guide for unauthenticated users and opens the composer modal for logged-in users
  const openComposerModal = useCallback(() => {
    if (!isLoggedIn) {
      showToast("プロンプトを投稿するにはログインが必要です。", { variant: "error" });
      return;
    }

    setPromptPostStatus("カテゴリやタイトルを軽く入れてから AI 補助を使うと、提案が安定します。", "info");
    openModal("post", promptPostTitleInputRef.current);
  }, [isLoggedIn, openModal, setPromptPostStatus]);

  // カテゴリをクリックしたとき、検索中なら一覧をリセットしてから選択カテゴリを適用する
  // When a category is clicked, resets the search if active before applying the selected category
  const handleCategoryClick = useCallback(
    (category: string) => {
      setOpenDropdownPromptId(null);
      setSelectedCategory(category);
      const contentFormatToApply = selectedContentFormatFilterRef.current;
      const mediaTypeToApply = selectedMediaTypeFilterRef.current;

      if (searchInput.trim()) {
        setSearchInput("");
        void loadPrompts({ categoryToApply: category, contentFormatToApply, mediaTypeToApply });
        return;
      }

      setAppliedCategoryFilter(category);
      setSelectedCategoryTitle(getCategoryTitle(category));

      setPromptCountMeta(
        buildPromptCountMeta(promptsRef.current, category, contentFormatToApply, mediaTypeToApply)
      );
    },
    [buildPromptCountMeta, loadPrompts, searchInput]
  );

  // フォーマットフィルタをクリックしたとき、検索中なら再検索してフィルタを適用する
  // When a content format filter is clicked, re-searches if a query is active to apply the new filter
  const handleContentFormatFilterClick = useCallback(
    (contentFormatFilter: ContentFormatFilter) => {
      setOpenDropdownPromptId(null);
      setSelectedContentFormatFilter(contentFormatFilter);
      selectedContentFormatFilterRef.current = contentFormatFilter;
      const mediaTypeFilter = selectedMediaTypeFilterRef.current;

      if (activeSearchQuery.trim() || searchInput.trim()) {
        void searchPrompts({ contentFormatToApply: contentFormatFilter, mediaTypeToApply: mediaTypeFilter });
        return;
      }

      setPromptCountMeta(
        buildPromptCountMeta(
          promptsRef.current,
          selectedCategoryRef.current,
          contentFormatFilter,
          mediaTypeFilter
        )
      );
    },
    [activeSearchQuery, buildPromptCountMeta, searchInput, searchPrompts]
  );

  // メディアフィルタをクリックしたとき、検索中なら再検索してフィルタを適用する
  // When a media type filter is clicked, re-searches if a query is active to apply the new filter
  const handleMediaTypeFilterClick = useCallback(
    (mediaTypeFilter: MediaTypeFilter) => {
      setOpenDropdownPromptId(null);
      setSelectedMediaTypeFilter(mediaTypeFilter);
      selectedMediaTypeFilterRef.current = mediaTypeFilter;
      const contentFormatFilter = selectedContentFormatFilterRef.current;

      if (activeSearchQuery.trim() || searchInput.trim()) {
        void searchPrompts({ contentFormatToApply: contentFormatFilter, mediaTypeToApply: mediaTypeFilter });
        return;
      }

      setPromptCountMeta(
        buildPromptCountMeta(
          promptsRef.current,
          selectedCategoryRef.current,
          contentFormatFilter,
          mediaTypeFilter
        )
      );
    },
    [activeSearchQuery, buildPromptCountMeta, searchInput, searchPrompts]
  );

  // Enterキーで検索を実行する。デフォルトのフォーム送信を防止する
  // Triggers search on Enter key press; prevents the default form submission
  const handleSearchInputKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void searchPrompts();
      }
    },
    [searchPrompts]
  );

  // プロンプト投稿フォームのサブミットハンドラ。バリデーション後にFormDataを構築してAPIに送信する
  // Handles prompt composer form submission: validates inputs, builds FormData, and calls the API
  const handlePostSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();

      // 必須のフォーム要素が存在するかを確認する
      // Verify that all required form elements are present in the DOM
      if (
        !promptPostTitleInputRef.current ||
        !promptPostCategorySelectRef.current ||
        !promptPostContentTextareaRef.current
      ) {
        setPromptPostStatus(
          "フォーム要素が見つかりませんでした。ページを再読み込みしてください。",
          "error"
        );
        return;
      }

      if (isPostSubmitting) {
        return;
      }

      const referenceImageError = validateReferenceImageFile(referenceImageFile);
      if (referenceImageError) {
        setPromptPostStatus(referenceImageError, "error");
        return;
      }

      // 2軸とフォーマット固有の属性を選択的にFormDataへ追加する
      // Selectively append the two axes and format-specific attributes to FormData
      const isSkill = contentFormat === "skill";
      const includeExamples = !isSkill && guardrailEnabled;
      // レジストリが宣言するキーのみを属性として送る (JSON文字列)。
      // Send only the keys the format declares, as a JSON string.
      const attributes = buildAttributes(contentFormat, {
        skill_markdown: postSkillMarkdown,
        skill_python_script: postSkillPythonScript
      });

      const formData = new FormData();
      formData.append("title", postTitle);
      formData.append("category", postCategory);
      formData.append("content", isSkill ? "" : postContent);
      formData.append("content_format", contentFormat);
      formData.append("media_type", mediaType);
      formData.append("input_examples", includeExamples ? postInputExample : "");
      formData.append("output_examples", includeExamples ? postOutputExample : "");
      formData.append("ai_model", postAiModel);
      formData.append("attributes", JSON.stringify(attributes));

      if (mediaAllowsAttachment(mediaType) && referenceImageFile) {
        formData.append("reference_image", referenceImageFile);
      }

      setIsPostSubmitting(true);
      setPromptPostStatus("プロンプトを投稿しています...", "info");

      try {
        await createPrompt(formData);

        setPromptPostStatus("プロンプトが投稿されました。公開一覧へ反映します。", "success");

        // 投稿成功後にフォームを全フィールドリセットする
        // Reset all form fields after a successful submission
        setContentFormat("prompt");
        setMediaType("text");
        setPostTitle("");
        setPostCategory(CATEGORY_UNSET);
        setPostContent("");
        setPostAiModel("");
        setGuardrailEnabled(false);
        setPostInputExample("");
        setPostOutputExample("");
        setPostSkillMarkdown("");
        setPostSkillPythonScript("");
        clearPromptImageSelection();

        await loadPrompts({
          categoryToApply: selectedCategoryRef.current,
          contentFormatToApply: selectedContentFormatFilterRef.current,
          mediaTypeToApply: selectedMediaTypeFilterRef.current
        });

        // 成功メッセージをユーザーに見せてからモーダルを閉じるための短い遅延
        // Brief delay to let the user see the success message before auto-closing the modal
        if (postCloseTimerRef.current !== null) {
          window.clearTimeout(postCloseTimerRef.current);
        }
        postCloseTimerRef.current = window.setTimeout(() => {
          const closed = closeModal("post", { rotateTrigger: true });
          if (!closed) {
            setIsPostSubmitting(false);
          }
        }, 550);
      } catch (error) {
        console.error("投稿エラー:", error);
        setPromptPostStatus(
          error instanceof Error ? error.message : "プロンプト投稿中にエラーが発生しました。",
          "error"
        );
        setIsPostSubmitting(false);
      }
    },
    [
      clearPromptImageSelection,
      closeModal,
      guardrailEnabled,
      isPostSubmitting,
      loadPrompts,
      postAiModel,
      postCategory,
      postContent,
      postInputExample,
      postOutputExample,
      postSkillMarkdown,
      postSkillPythonScript,
      postTitle,
      contentFormat,
      mediaType,
      referenceImageFile,
      setPromptPostStatus,
      validateReferenceImageFile
    ]
  );

  // キャッシュからプロンプトをすぐに表示してから、APIで最新データを取得する（ストア・スワップ戦略）
  // Renders cached prompts immediately, then fetches fresh data from the API (stale-while-revalidate)
  useEffect(() => {
    const cachedPrompts = readPromptCache();
    if (cachedPrompts && cachedPrompts.length > 0) {
      const normalizedCache = cachedPrompts.map(normalizePromptData);
      const promptRecords = toPromptRecords(normalizedCache);
      setPrompts(promptRecords);
      setPromptFeedback(null);
      setIsPromptsLoading(false);
      setPromptCountMeta(
        buildPromptCountMeta(
          promptRecords,
          "all",
          selectedContentFormatFilterRef.current,
          selectedMediaTypeFilterRef.current
        )
      );
    }

    void loadPrompts();
  }, [buildPromptCountMeta, loadPrompts, toPromptRecords]);

  // 2軸が変わったときにAI補助パネルの表示を（派生した旧タイプで）更新する
  // Updates the AI-assist panel display whenever the axes change, using the derived legacy type
  useEffect(() => {
    promptAssistControllerRef.current?.updateForPromptType(
      deriveLegacyPromptType(contentFormat, mediaType)
    );
  }, [contentFormat, mediaType]);

  // ドキュメント全体のクリックでドロップダウンを閉じる。バブリングを利用した実装
  // Closes any open dropdown on document click, leveraging event bubbling
  useEffect(() => {
    const handleDocumentClick = () => {
      setOpenDropdownPromptId(null);
    };
    document.addEventListener("click", handleDocumentClick);
    return () => {
      document.removeEventListener("click", handleDocumentClick);
    };
  }, []);

  // 投稿フォームの全フィールドがDOMにマウントされてからAI補助パネルを一度だけ初期化する
  // Initializes the AI-assist panel exactly once after all composer form fields are mounted in the DOM
  useEffect(() => {
    if (!promptAssistRootRef.current || promptAssistInitializedRef.current) {
      return;
    }
    if (
      !promptPostTitleInputRef.current ||
      !promptPostCategorySelectRef.current ||
      !promptPostContentTextareaRef.current ||
      !promptPostAiModelSelectRef.current ||
      !promptPostInputExamplesRef.current ||
      !promptPostOutputExamplesRef.current ||
      !promptPostSkillMarkdownRef.current ||
      !promptPostSkillPythonScriptRef.current
    ) {
      return;
    }

    const controller = initPromptAssist({
      root: promptAssistRootRef.current,
      target: "shared_prompt_modal",
      fields: {
        title: { label: "タイトル", element: promptPostTitleInputRef.current, setValue: setPostTitle },
        category: { label: "カテゴリ", element: promptPostCategorySelectRef.current, setValue: setPostCategory },
        content: { label: "プロンプト内容", element: promptPostContentTextareaRef.current, setValue: setPostContent },
        skill_markdown: {
          label: "SKILL定義",
          element: promptPostSkillMarkdownRef.current,
          setValue: setPostSkillMarkdown
        },
        skill_python_script: {
          label: "追加Pythonスクリプト",
          element: promptPostSkillPythonScriptRef.current,
          setValue: setPostSkillPythonScript
        },
        ai_model: { label: "使用AIモデル", element: promptPostAiModelSelectRef.current, setValue: setPostAiModel },
        prompt_type: {
          label: "互換タイプ",
          element: null,
          getValue: () => promptTypeRef.current
        },
        input_examples: { label: "入力例", element: promptPostInputExamplesRef.current, setValue: setPostInputExample },
        output_examples: { label: "出力例", element: promptPostOutputExamplesRef.current, setValue: setPostOutputExample }
      },
      beforeApplyField: (fieldName) => {
        // 入力例や出力例が自動入力されるときにガードレールを自動的に有効化する
        // Auto-enables guardrails when AI-assist populates input/output examples
        if (fieldName === "input_examples" || fieldName === "output_examples") {
          setGuardrailEnabled(true);
        }
      }
    });

    promptAssistControllerRef.current = controller || null;
    promptAssistInitializedRef.current = true;

    return () => {
      promptAssistControllerRef.current = null;
      promptAssistInitializedRef.current = false;
    };
  }, []);

  // コメントビューが開いたときにテキストエリアへフォーカスしてスムーズにスクロールする
  // Scrolls to and focuses the comment textarea when the comments view becomes active
  useEffect(() => {
    if (activeModal !== "detail" || detailModalView !== "comments") {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      const target = promptCommentTextareaRef.current || promptCommentsSectionRef.current;
      if (!target) {
        return;
      }
      target.focus({ preventScroll: true });
      promptCommentsSectionRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [activeModal, detailModalView, detailPrompt]);

  // フィルタ適用後に表示件数がゼロになった場合のフィードバックを生成する（読み込み中は非表示）
  // Generates empty-filter feedback when visible prompts drop to zero after filtering (hidden during loading)
  const filterEmptyFeedback = useMemo<PromptFeedback | null>(() => {
    if (isPromptsLoading || promptFeedback || prompts.length === 0 || visiblePrompts.length > 0) {
      return null;
    }
    return {
      message: getFilterEmptyMessage(
        selectedContentFormatFilterRef.current,
        selectedMediaTypeFilterRef.current
      ),
      variant: "empty"
    };
  }, [isPromptsLoading, promptFeedback, prompts.length, visiblePrompts.length]);

  // APIエラーやフィルタの空状態などを統合して、表示するフィードバックを一本化する
  // Consolidates API error feedback and filter-empty feedback into a single value to display
  const showPromptFeedback = Boolean(promptFeedback && visiblePrompts.length === 0 && !isPromptsLoading);
  const feedbackToShow = showPromptFeedback ? promptFeedback : filterEmptyFeedback;

  return (
    <>
      {/* SEOメタタグと構造化データを設定するヘッドコンポーネント / Head component that sets SEO meta tags and structured data */}
      <SeoHead
        title="プロンプト共有 | Chat Core"
        description={promptShareDescription}
        canonicalPath="/prompt_share"
        structuredData={promptShareStructuredData}
      />

      {/* プロンプト一覧・検索・フィルタを含むページレイアウト / Page layout containing the prompt list, search bar, and filters */}
      <PromptSharePageLayout
        authUiReady={authUiReady}
        isLoggedIn={isLoggedIn}
        searchInput={searchInput}
        onSearchInputChange={setSearchInput}
        onSearchInputKeyDown={handleSearchInputKeyDown}
        onSearch={() => {
          void searchPrompts();
        }}
        onOpenComposerModal={openComposerModal}
        categories={PROMPT_CATEGORIES}
        selectedCategory={selectedCategory}
        onCategoryClick={handleCategoryClick}
        contentFormatFilters={PROMPT_CONTENT_FORMAT_FILTERS}
        selectedContentFormatFilter={selectedContentFormatFilter}
        onContentFormatFilterClick={handleContentFormatFilterClick}
        mediaTypeFilters={PROMPT_MEDIA_TYPE_FILTERS}
        selectedMediaTypeFilter={selectedMediaTypeFilter}
        onMediaTypeFilterClick={handleMediaTypeFilterClick}
        selectedCategoryTitle={selectedCategoryTitle}
        promptCountMeta={promptCountMeta}
        hasMoreSearchResults={hasMoreSearchResults}
        isLoadingMoreSearchResults={isLoadingMoreSearchResults}
        onLoadMoreSearchResults={() => {
          void loadMoreSearchResults();
        }}
        isPromptsLoading={isPromptsLoading}
        hasPromptFeedback={Boolean(promptFeedback)}
        visiblePrompts={visiblePrompts}
        feedbackToShow={feedbackToShow}
        openDropdownPromptId={openDropdownPromptId}
        likePendingIds={likePendingIds}
        actionEffectIds={actionEffectIds}
        addAsTaskPendingIds={addAsTaskPendingIds}
        onOpenDetail={openPromptDetailModal}
        onOpenComments={openPromptCommentsModal}
        onOpenShare={openPromptShareDialog}
        onToggleDropdown={togglePromptDropdown}
        onCloseDropdown={closePromptDropdown}
        onAddAsTask={handleAddPromptAsTask}
        onToggleLike={handleTogglePromptLike}
      >

        {/* プロンプト投稿フォームのモーダル。ログイン済みユーザーのみ利用可能 / Composer modal for posting new prompts; only available to logged-in users */}
        <PromptShareComposerModal
          isOpen={activeModal === "post"}
          isPostSubmitting={isPostSubmitting}
          postModalRef={postModalRef}
          onClose={() => {
            closeModal("post", { rotateTrigger: true });
          }}
          onSubmit={handlePostSubmit}
          contentFormat={contentFormat}
          setContentFormat={setContentFormat}
          mediaType={mediaType}
          setMediaType={setMediaType}
          postTitle={postTitle}
          setPostTitle={setPostTitle}
          postCategory={postCategory}
          setPostCategory={setPostCategory}
          postContent={postContent}
          setPostContent={setPostContent}
          postAiModel={postAiModel}
          setPostAiModel={setPostAiModel}
          guardrailEnabled={guardrailEnabled}
          setGuardrailEnabled={setGuardrailEnabled}
          postInputExample={postInputExample}
          setPostInputExample={setPostInputExample}
          postOutputExample={postOutputExample}
          setPostOutputExample={setPostOutputExample}
          attributeBindings={{
            skill_markdown: {
              value: postSkillMarkdown,
              setValue: setPostSkillMarkdown,
              ref: promptPostSkillMarkdownRef
            },
            skill_python_script: {
              value: postSkillPythonScript,
              setValue: setPostSkillPythonScript,
              ref: promptPostSkillPythonScriptRef
            }
          }}
          updatePromptFeedbackErrorIfNeeded={updatePromptFeedbackErrorIfNeeded}
          categoryOptions={PROMPT_CATEGORY_OPTIONS}
          promptPostStatus={promptPostStatus}
          promptPostTitleInputRef={promptPostTitleInputRef}
          promptPostCategorySelectRef={promptPostCategorySelectRef}
          promptPostContentTextareaRef={promptPostContentTextareaRef}
          promptPostAiModelSelectRef={promptPostAiModelSelectRef}
          promptPostInputExamplesRef={promptPostInputExamplesRef}
          promptPostOutputExamplesRef={promptPostOutputExamplesRef}
          promptImageInputRef={promptImageInputRef}
          promptAssistRootRef={promptAssistRootRef}
          promptImagePreviewUrl={promptImagePreviewUrl}
          promptImagePreviewName={promptImagePreviewName}
          onReferenceImageChange={handleReferenceImageChange}
          onClearReferenceImage={clearPromptImageSelection}
        />

        {/* プロンプト詳細とコメント一覧を表示するモーダル / Modal showing prompt details and the comment thread */}
        <PromptShareDetailModal
          isOpen={activeModal === "detail"}
          isLoggedIn={isLoggedIn}
          activeView={detailModalView}
          promptDetailModalRef={promptDetailModalRef}
          commentsSectionRef={promptCommentsSectionRef}
          commentTextareaRef={promptCommentTextareaRef}
          detailPrompt={detailPrompt}
          detailComments={detailComments}
          isDetailCommentsLoading={isDetailCommentsLoading}
          isCommentSubmitting={isCommentSubmitting}
          commentDraft={commentDraft}
          commentActionPendingIds={commentActionPendingIds}
          promptDetailCloseButtonRef={promptDetailCloseButtonRef}
          onActiveViewChange={setDetailModalView}
          onCommentDraftChange={setCommentDraft}
          onSubmitComment={handleSubmitPromptComment}
          onDeleteComment={handleDeletePromptComment}
          onReportComment={handleReportPromptComment}
          onReloadComments={reloadDetailComments}
          onClose={() => {
            closeModal("detail");
          }}
        />

        {/* 共有URLとSNSリンクを表示するモーダル / Modal displaying the share URL and SNS share links */}
        <PromptShareShareModal
          isOpen={activeModal === "share"}
          promptShareModalRef={promptShareModalRef}
          onClose={() => {
            closeModal("share");
          }}
          shareUrl={shareUrl}
          shareStatus={shareStatus}
          shareActionLoading={shareActionLoading}
          promptShareCopyButtonRef={promptShareCopyButtonRef}
          onCopyLink={handleCopyShareLink}
          supportsNativeShare={supportsNativeShare}
          onNativeShare={handleNativeShare}
          shareSnsLinks={shareSnsLinks}
        />

      </PromptSharePageLayout>
    </>
  );
}
