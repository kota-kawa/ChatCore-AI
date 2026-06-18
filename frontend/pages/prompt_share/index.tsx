import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent
} from "react";
import type { GetServerSideProps } from "next";

import { SeoHead } from "../../components/SeoHead";
import "../../scripts/core/csrf";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { showToast } from "../../scripts/core/toast";
import { copyTextToClipboard } from "../../scripts/chat/message_utils";
import { initPromptAssist } from "../../scripts/components/prompt_assist";
import { setLoggedInState } from "../../scripts/core/app_state";
import {
  createPrompt,
  createPromptComment,
  deletePromptComment,
  fetchPromptComments,
  fetchPromptList,
  fetchPromptSearchResults,
  reportPromptComment,
  addPromptAsTask,
  removePromptAsTask,
  removePromptLike,
  savePromptLike
} from "../../scripts/prompt_share/api";
import {
  ACCEPTED_PROMPT_IMAGE_EXTENSIONS,
  ACCEPTED_PROMPT_IMAGE_TYPES,
  PROMPT_IMAGE_MAX_BYTES,
  PROMPT_SHARE_TEXT,
  PROMPT_SHARE_TITLE
} from "../../scripts/prompt_share/constants";
import { normalizePromptData, normalizePromptType } from "../../scripts/prompt_share/formatters";
import {
  readCachedAuthState,
  readPromptCache,
  writeCachedAuthState,
  writePromptCache
} from "../../scripts/prompt_share/storage";
import type {
  PromptCommentData,
  PromptData,
  PromptFeedResponse,
  PromptPagination,
  PromptType
} from "../../scripts/prompt_share/types";
import { PromptShareComposerModal } from "../../components/prompt_share/prompt_share_composer_modal";
import { PromptShareDetailModal } from "../../components/prompt_share/prompt_share_detail_modal";
import {
  PROMPT_CATEGORIES,
  PROMPT_CATEGORY_OPTIONS,
  PROMPT_TYPE_FILTERS,
  SEARCH_RESULTS_PER_PAGE
} from "../../components/prompt_share/prompt_share_page_constants";
import { PromptSharePageLayout } from "../../components/prompt_share/prompt_share_page_layout";
import type {
  ModalKey,
  PromptFeedback,
  PromptPostStatus,
  PromptPostStatusVariant,
  PromptTypeFilter
} from "../../components/prompt_share/prompt_share_page_types";
import {
  getCategoryCountLabel,
  getCategoryTitle,
  getModalFocusableElements,
  getPromptId
} from "../../components/prompt_share/prompt_share_page_utils";
import { PromptShareShareModal } from "../../components/prompt_share/prompt_share_share_modal";
import type { PromptRecord } from "../../components/prompt_share/prompt_card";
import { absoluteUrl } from "../../lib/seo";

// SEO向けのページ説明文。検索エンジンのスニペットとして表示される
// Page description for SEO; displayed as the search engine snippet
const promptShareDescription =
  "Chat Coreのプロンプト共有ページです。文章作成、調査、画像生成などに使える日本語AIプロンプトを探して、保存して、共有できます。";

// 構造化データ（JSON-LD）。Googleがリッチリザルトとしてページを解釈できるようにする
// Structured data (JSON-LD) that helps Google understand and display this page as a rich result
const promptShareStructuredData = {
  "@context": "https://schema.org",
  "@type": "CollectionPage",
  name: "Chat Core プロンプト共有",
  url: absoluteUrl("/prompt_share"),
  description: promptShareDescription,
  inLanguage: "ja",
  isPartOf: {
    "@type": "WebSite",
    name: "Chat Core",
    url: absoluteUrl("/")
  }
};

type PromptSharePageProps = {
  initialPrompts?: PromptData[];
};

// SSRで事前取得するプロンプトの最大件数。初期表示の速度とデータ量のバランスをとるための定数
// Maximum number of prompts fetched during SSR; balances initial render speed against payload size
const INITIAL_PROMPT_LIMIT = 18;

// バックエンドのオリジンを環境変数から取得し、末尾スラッシュを除去する
// Reads the backend origin from the environment variable and strips any trailing slashes
function getBackendOrigin() {
  return (process.env.BACKEND_URL || "http://localhost:5004").replace(/\/+$/, "");
}

// SSR時にプロンプト一覧を事前取得する。失敗した場合でも空配列でページを返し、CSRで再取得させる
// Pre-fetches the prompt list at SSR time; returns an empty array on failure so the client can retry
export const getServerSideProps: GetServerSideProps<PromptSharePageProps> = async () => {
  try {
    const response = await fetch(`${getBackendOrigin()}/prompt_share/api/prompts`, {
      headers: {
        "Accept": "application/json"
      }
    });
    if (!response.ok) {
      return { props: { initialPrompts: [] } };
    }

    const data = await response.json() as PromptFeedResponse;
    // 件数上限を適用し、クライアント側で使いやすい形式に正規化する
    // Apply the item limit and normalize into the client-friendly format
    const initialPrompts = Array.isArray(data.prompts)
      ? data.prompts.slice(0, INITIAL_PROMPT_LIMIT).map(normalizePromptData)
      : [];

    return { props: { initialPrompts } };
  } catch (error) {
    console.error("Failed to load prompt share SSR prompts:", error);
    return { props: { initialPrompts: [] } };
  }
};

// プロンプト共有ページのメインコンポーネント。検索・フィルタ・モーダル・いいね・チャット追加など全機能を管理する
// Main component for the prompt share page; manages search, filters, modals, likes, use-in-chat, and all other features
export default function PromptSharePage({ initialPrompts = [] }: PromptSharePageProps) {
  // SSRで受け取った初期プロンプトをクライアント用レコード形式に変換する（マウント時のみ実行）
  // Transforms SSR-provided prompts into client records on mount only, avoiding unnecessary recomputation
  const initialPromptRecords = useMemo<PromptRecord[]>(() => {
    return initialPrompts.map((item, index) => ({
      ...normalizePromptData(item),
      clientId: `prompt-initial-${String(item.id ?? index)}`,
      liked: Boolean(item.liked),
      used_in_chat: Boolean(item.used_in_chat)
    }));
  }, [initialPrompts]);

  // 認証状態の管理。キャッシュから即座にUIを表示し、API確認後に最新の状態へ更新する
  // Auth state management: shows UI immediately from cache, then syncs with the API
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [authUiReady, setAuthUiReady] = useState(false);
  const [supportsNativeShare, setSupportsNativeShare] = useState(false);

  // 検索・フィルタ関連の状態
  // Search and filter state
  const [searchInput, setSearchInput] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [selectedCategoryTitle, setSelectedCategoryTitle] = useState("全てのプロンプト");
  const [appliedCategoryFilter, setAppliedCategoryFilter] = useState<string | null>("all");
  const [selectedPromptTypeFilter, setSelectedPromptTypeFilter] = useState<PromptTypeFilter>("all");

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
  const [activeModal, setActiveModal] = useState<ModalKey>(null);
  const [detailModalView, setDetailModalView] = useState<"detail" | "comments">("detail");
  const [detailPrompt, setDetailPrompt] = useState<PromptRecord | null>(null);
  const [detailComments, setDetailComments] = useState<PromptCommentData[]>([]);
  const [isDetailCommentsLoading, setIsDetailCommentsLoading] = useState(false);
  const [isCommentSubmitting, setIsCommentSubmitting] = useState(false);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentActionPendingIds, setCommentActionPendingIds] = useState<Set<string>>(new Set());
  const [shareUrl, setShareUrl] = useState("");
  const [shareStatus, setShareStatus] = useState({
    text: "共有するプロンプトを選択してください。",
    isError: false
  });
  const [shareActionLoading, setShareActionLoading] = useState(false);

  // カードのドロップダウンとアクションの保留中IDを追跡する
  // Tracks open card dropdown and pending action IDs to prevent duplicate requests
  const [openDropdownPromptId, setOpenDropdownPromptId] = useState<string | null>(null);
  const [likePendingIds, setLikePendingIds] = useState<Set<string>>(new Set());
  const [actionEffectIds, setActionEffectIds] = useState<Set<string>>(new Set());
  const [addAsTaskPendingIds, setAddAsTaskPendingIds] = useState<Set<string>>(new Set());

  // 投稿フォームの各フィールドの状態
  // Composer form field states
  const [promptType, setPromptType] = useState<PromptType>("text");
  const [postTitle, setPostTitle] = useState("");
  const [postCategory, setPostCategory] = useState("未選択");
  const [postContent, setPostContent] = useState("");
  const [postAiModel, setPostAiModel] = useState("");
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [postInputExample, setPostInputExample] = useState("");
  const [postOutputExample, setPostOutputExample] = useState("");
  const [postSkillMarkdown, setPostSkillMarkdown] = useState("");
  const [postSkillPythonScript, setPostSkillPythonScript] = useState("");
  const [referenceImageFile, setReferenceImageFile] = useState<File | null>(null);
  const [promptImagePreviewUrl, setPromptImagePreviewUrl] = useState("");
  const [promptImagePreviewName, setPromptImagePreviewName] = useState("");
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
  const selectedPromptTypeFilterRef = useRef<PromptTypeFilter>("all");
  const activeModalRef = useRef<ModalKey>(null);

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

  const promptImageInputRef = useRef<HTMLInputElement | null>(null);

  // AI補助パネルの制御。一度だけ初期化し、プロンプトタイプ変更時に更新する
  // AI-assist panel control; initialized once and updated when prompt type changes
  const promptAssistRootRef = useRef<HTMLDivElement | null>(null);
  const promptAssistInitializedRef = useRef(false);
  const promptAssistControllerRef = useRef<{ reset: () => void; updateForPromptType: (t: string) => void } | null>(null);
  const promptTypeRef = useRef<PromptType>("text");
  const likePendingIdsRef = useRef<Set<string>>(new Set());
  // アニメーション効果のタイマーIDを管理し、素早い連続操作でタイマーが積み重ならないようにする
  // Stores animation effect timer IDs to cancel previous timers on rapid successive actions
  const actionEffectTimersRef = useRef<Map<string, number>>(new Map());

  const promptDetailCloseButtonRef = useRef<HTMLButtonElement | null>(null);
  const promptShareCopyButtonRef = useRef<HTMLButtonElement | null>(null);

  // モーダル開閉時のフォーカス復元とスクロール位置の保存に使用する
  // Used to restore focus and save scroll position when modals open/close
  const previousFocusedElementRef = useRef<HTMLElement | null>(null);
  const preferredFocusElementRef = useRef<HTMLElement | null>(null);
  const lockedScrollYRef = useRef(0);
  const hasModalLockRef = useRef(false);

  const promptImagePreviewUrlRef = useRef("");
  // 投稿後にモーダルを自動で閉じるタイマーの参照
  // Reference to the timer that auto-closes the composer modal after a successful post
  const postCloseTimerRef = useRef<number | null>(null);
  const cachedPromptShareUrlsRef = useRef<Map<string, string>>(new Map());
  const detailPromptIdRef = useRef("");

  // stateが変わるたびにRefを同期する。これにより非同期コールバック内でも最新値を参照できる
  // Syncs refs whenever state changes so async callbacks always see the latest values
  useEffect(() => {
    promptsRef.current = prompts;
  }, [prompts]);

  useEffect(() => {
    selectedCategoryRef.current = selectedCategory;
  }, [selectedCategory]);

  useEffect(() => {
    selectedPromptTypeFilterRef.current = selectedPromptTypeFilter;
  }, [selectedPromptTypeFilter]);

  useEffect(() => {
    activeModalRef.current = activeModal;
  }, [activeModal]);

  useEffect(() => {
    promptTypeRef.current = promptType;
  }, [promptType]);

  // コンポーネントのアンマウント時に残存するアニメーションタイマーを全てクリアする
  // Clears all lingering animation timers when the component unmounts
  useEffect(() => {
    return () => {
      actionEffectTimersRef.current.forEach((timerId) => {
        window.clearTimeout(timerId);
      });
      actionEffectTimersRef.current.clear();
    };
  }, []);

  // PromptRecordからキャッシュ保存用のデータ形式に変換する（クライアント専用のclientIdを除外）
  // Strips the client-only clientId field to produce a cacheable representation
  const toCachedPromptData = useCallback((items: PromptRecord[]) => {
    return items.map(({ clientId, ...prompt }) => prompt);
  }, []);

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

  // 画像プレビューのObject URLを解放してメモリリークを防ぐ
  // Revokes the image preview Object URL to prevent memory leaks
  const revokePromptImagePreview = useCallback(() => {
    if (!promptImagePreviewUrlRef.current) {
      return;
    }
    URL.revokeObjectURL(promptImagePreviewUrlRef.current);
    promptImagePreviewUrlRef.current = "";
  }, []);

  // 選択中の画像ファイルとプレビューを全て削除し、inputの値もリセットする
  // Removes the selected image file, clears the preview, and resets the file input value
  const clearPromptImageSelection = useCallback(() => {
    revokePromptImagePreview();
    setReferenceImageFile(null);
    setPromptImagePreviewUrl("");
    setPromptImagePreviewName("");
    if (promptImageInputRef.current) {
      promptImageInputRef.current.value = "";
    }
  }, [revokePromptImagePreview]);

  // ファイルの拡張子とMIMEタイプおよびサイズを検証する
  // Validates the file's extension, MIME type, and size against allowed values
  const validateReferenceImageFile = useCallback((file: File | null) => {
    if (!file) return null;
    const lowerName = file.name.toLowerCase();
    const hasAcceptedExtension = ACCEPTED_PROMPT_IMAGE_EXTENSIONS.some((ext) =>
      lowerName.endsWith(ext)
    );
    if (!ACCEPTED_PROMPT_IMAGE_TYPES.has(file.type) && !hasAcceptedExtension) {
      return "画像は PNG / JPG / WebP / GIF のいずれかを指定してください。";
    }
    if (file.size > PROMPT_IMAGE_MAX_BYTES) {
      return "画像サイズは5MB以下にしてください。";
    }
    return null;
  }, []);

  // 新しいファイルが選択された際に以前のObject URLを解放してから新しいプレビューを生成する
  // Revokes the previous Object URL before generating a new preview to avoid accumulating blob URLs
  const updatePromptImagePreview = useCallback(
    (file: File | null) => {
      if (!file) {
        clearPromptImageSelection();
        return;
      }
      revokePromptImagePreview();
      const nextUrl = URL.createObjectURL(file);
      promptImagePreviewUrlRef.current = nextUrl;
      setReferenceImageFile(file);
      setPromptImagePreviewUrl(nextUrl);
      setPromptImagePreviewName(`${file.name} (${Math.max(1, Math.round(file.size / 1024))}KB)`);
    },
    [clearPromptImageSelection, revokePromptImagePreview]
  );

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

  // フィルタ値からUI表示用のラベル文字列を取得する
  // Returns the display label for a given prompt type filter value
  const getPromptTypeFilterLabel = useCallback((promptTypeFilter: PromptTypeFilter) => {
    return PROMPT_TYPE_FILTERS.find((option) => option.value === promptTypeFilter)?.label || "全て";
  }, []);

  // カテゴリとプロンプトタイプの両方の条件でプロンプト一覧をフィルタリングする
  // Filters the prompt list by both category and prompt type simultaneously
  const filterPrompts = useCallback(
    (items: PromptRecord[], category: string | null, promptTypeFilter: PromptTypeFilter) => {
      return items.filter((item) => {
        const categoryMatches = !category || category === "all" || (item.category || "") === category;
        const promptTypeMatches =
          promptTypeFilter === "all" || normalizePromptType(item.prompt_type) === promptTypeFilter;
        return categoryMatches && promptTypeMatches;
      });
    },
    []
  );

  // 現在のフィルタ条件に一致する表示件数を算出する
  // Counts how many prompts are visible under the current filter conditions
  const countVisiblePrompts = useCallback(
    (items: PromptRecord[], category: string | null, promptTypeFilter: PromptTypeFilter) => {
      return filterPrompts(items, category, promptTypeFilter).length;
    },
    [filterPrompts]
  );

  // 現在のフィルタ・検索結果に応じてカウント表示文字列を構築する
  // Builds the count display string based on current filters and search results
  const buildPromptCountMeta = useCallback(
    (
      items: PromptRecord[],
      category: string | null,
      promptTypeFilter: PromptTypeFilter,
      options?: { searchTotal?: number }
    ) => {
      const visibleCount = countVisiblePrompts(items, category, promptTypeFilter);
      const typeSuffix = promptTypeFilter === "all" ? "" : ` / ${getPromptTypeFilterLabel(promptTypeFilter)}`;

      if (typeof options?.searchTotal === "number") {
        return `検索結果${typeSuffix}: ${visibleCount}件 / ${options.searchTotal}件`;
      }

      return `${getCategoryCountLabel(category || "all")}${typeSuffix}: ${visibleCount}件`;
    },
    [countVisiblePrompts, getPromptTypeFilterLabel]
  );

  // フィルタ結果が0件だった場合にプロンプトタイプを含む適切なメッセージを返す
  // Returns an appropriate empty-state message that includes the active prompt type filter
  const getFilterEmptyMessage = useCallback(() => {
    if (selectedPromptTypeFilterRef.current === "all") {
      return "条件に一致するプロンプトが見つかりませんでした。";
    }
    return `${getPromptTypeFilterLabel(selectedPromptTypeFilterRef.current)}のプロンプトが見つかりませんでした。`;
  }, [getPromptTypeFilterLabel]);

  // カテゴリとプロンプトタイプでフィルタリングした後の表示対象プロンプト一覧
  // Derived list of prompts visible after applying category and prompt type filters
  const visiblePrompts = useMemo(() => {
    return filterPrompts(prompts, appliedCategoryFilter, selectedPromptTypeFilter);
  }, [filterPrompts, prompts, appliedCategoryFilter, selectedPromptTypeFilter]);

  // 検索中かつ次ページが存在する場合に「もっと見る」ボタンを表示する
  // Indicates whether a "load more" button should be shown for search results
  const hasMoreSearchResults =
    activeSearchQuery.trim().length > 0 && Boolean(searchPagination?.has_next);

  // SNS共有リンクを共有URLから動的に生成する。URLが未設定の場合は無効なリンクを返す
  // Derives SNS share links from the share URL; returns placeholder links if none is set
  const shareSnsLinks = useMemo(() => {
    if (!shareUrl) {
      return {
        x: "#",
        line: "#",
        facebook: "#"
      };
    }
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent(PROMPT_SHARE_TEXT);
    return {
      x: `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`,
      line: `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`,
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`
    };
  }, [shareUrl]);

  // モーダルキーからDOMのref要素へのマッピングを提供する
  // Maps a modal key to its corresponding DOM ref element
  const getModalElement = useCallback((modal: Exclude<ModalKey, null>) => {
    if (modal === "post") return postModalRef.current;
    if (modal === "detail") return promptDetailModalRef.current;
    return promptShareModalRef.current;
  }, []);

  // モーダル内のフォーカス可能な要素を取得し、優先要素または先頭要素へフォーカスを移す
  // Finds focusable elements inside a modal and moves focus to the preferred or first element
  const focusModal = useCallback(
    (modal: Exclude<ModalKey, null>) => {
      const modalElement = getModalElement(modal);
      if (!modalElement) {
        return;
      }

      const focusableElements = getModalFocusableElements(modalElement);
      const preferredElement = preferredFocusElementRef.current;
      const fallbackTarget =
        modalElement.querySelector<HTMLElement>(".post-modal-content") || modalElement;

      const target =
        (preferredElement && focusableElements.includes(preferredElement) ? preferredElement : null) ||
        focusableElements[0] ||
        fallbackTarget;

      window.requestAnimationFrame(() => {
        target.focus();
      });
    },
    [getModalElement]
  );

  // 投稿モーダルのステータスと送信中フラグをリセットし、AI補助パネルも初期状態へ戻す
  // Resets the post modal status, the submitting flag, and the AI-assist panel to their initial states
  const resetPostModalState = useCallback(() => {
    setPromptPostStatus("", "info");
    setIsPostSubmitting(false);
    promptAssistControllerRef.current?.reset();
  }, [setPromptPostStatus]);

  // 指定されたモーダルを閉じ、詳細モーダルの場合はコメント関連の状態も全てクリアする
  // Closes the specified modal and, for the detail modal, also clears all comment-related state
  const closeModal = useCallback(
    (modal: Exclude<ModalKey, null>, options?: { rotateTrigger?: boolean }) => {
      if (activeModalRef.current !== modal) {
        return false;
      }

      setActiveModal(null);
      if (modal === "post") {
        resetPostModalState();
      } else if (modal === "detail") {
        setDetailModalView("detail");
        detailPromptIdRef.current = "";
        setDetailPrompt(null);
        setDetailComments([]);
        setCommentDraft("");
        setCommentActionPendingIds(new Set());
        setIsDetailCommentsLoading(false);
        setIsCommentSubmitting(false);
      }
      return true;
    },
    [resetPostModalState]
    );


  // モーダルを開く前にトリガー要素を記録しておき、閉じた後にフォーカスを元の位置へ戻せるようにする
  // Records the trigger element before opening so focus can be restored when the modal closes
  const openModal = useCallback((modal: Exclude<ModalKey, null>, preferredElement?: HTMLElement | null) => {
    previousFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    preferredFocusElementRef.current = preferredElement || null;
    setActiveModal(modal);
  }, []);

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

  // いいね操作のAPIリクエスト中に重複送信を防ぐためのフラグを管理する
  // Manages a pending flag to prevent duplicate like API requests
  const setLikePending = useCallback((clientId: string, pending: boolean) => {
    if (pending) {
      likePendingIdsRef.current.add(clientId);
    } else {
      likePendingIdsRef.current.delete(clientId);
    }
    setLikePendingIds(new Set(likePendingIdsRef.current));
  }, []);

  // いいね時のアニメーション効果を発火させ、一定時間後に自動解除する
  // Triggers a visual animation effect and automatically removes it after a fixed duration
  const triggerActionEffect = useCallback((effectId: string) => {
    const activeTimerId = actionEffectTimersRef.current.get(effectId);
    if (activeTimerId) {
      window.clearTimeout(activeTimerId);
    }

    setActionEffectIds((current) => {
      const next = new Set(current);
      next.add(effectId);
      return next;
    });

    const timerId = window.setTimeout(() => {
      actionEffectTimersRef.current.delete(effectId);
      setActionEffectIds((current) => {
        const next = new Set(current);
        next.delete(effectId);
        return next;
      });
    }, 720);

    actionEffectTimersRef.current.set(effectId, timerId);
  }, []);

  // タスク追加の非同期処理中に重複リクエストを防ぐためのフラグを管理する
  // Manages a pending flag to prevent duplicate add-as-task requests
  const setAddAsTaskPending = useCallback((clientId: string, pending: boolean) => {
    setAddAsTaskPendingIds((current) => {
      const next = new Set(current);
      if (pending) {
        next.add(clientId);
      } else {
        next.delete(clientId);
      }
      return next;
    });
  }, []);

  // コメントの削除・報告操作の処理中に重複リクエストを防ぐためのフラグを管理する
  // Manages pending flags for comment delete/report operations to avoid duplicate requests
  const setCommentActionPending = useCallback((commentId: string, pending: boolean) => {
    setCommentActionPendingIds((current) => {
      const next = new Set(current);
      if (pending) {
        next.add(commentId);
      } else {
        next.delete(commentId);
      }
      return next;
    });
  }, []);

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
    [toCachedPromptData]
  );

  // APIからプロンプト一覧を取得し、フィルタ状態を適用した上でキャッシュに書き込む
  // Fetches the full prompt list from the API, applies filter state, and writes the result to cache
  const loadPrompts = useCallback(
    async (options?: { categoryToApply?: string; promptTypeToApply?: PromptTypeFilter }) => {
      const categoryToApply = options?.categoryToApply || selectedCategoryRef.current;
      const promptTypeToApply = options?.promptTypeToApply || selectedPromptTypeFilterRef.current;
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
        setSelectedPromptTypeFilter(promptTypeToApply);
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

        setPromptCountMeta(buildPromptCountMeta(promptRecords, categoryToApply, promptTypeToApply));
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
  const searchPrompts = useCallback(async (options?: { promptTypeToApply?: PromptTypeFilter }) => {
    const query = searchInput.trim();
    const promptTypeToApply = options?.promptTypeToApply || selectedPromptTypeFilterRef.current;

    if (!query) {
      setSelectedCategoryTitle("全てのプロンプト");
      await loadPrompts({ promptTypeToApply });
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
        promptType: promptTypeToApply
      });
      const normalizedPrompts = Array.isArray(data.prompts)
        ? data.prompts.map(normalizePromptData)
        : [];
      const promptRecords = toPromptRecords(normalizedPrompts);

      setPrompts(promptRecords);
      setSelectedPromptTypeFilter(promptTypeToApply);
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
        buildPromptCountMeta(promptRecords, null, promptTypeToApply, {
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
        promptType: selectedPromptTypeFilterRef.current
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
        buildPromptCountMeta(nextPrompts, null, selectedPromptTypeFilterRef.current, {
          searchTotal: Number(data.pagination?.total || nextPrompts.length)
        })
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

  // プロンプトIDをもとに外部共有用のパーマリンクを生成する
  // Generates a permanent shareable link from the prompt's ID
  const buildPromptShareUrl = useCallback((prompt: PromptRecord | null) => {
    const promptId = getPromptId(prompt);
    if (!promptId) {
      throw new Error("共有対象のプロンプトIDが見つかりません。");
    }
    return `${window.location.origin}/shared/prompt/${encodeURIComponent(promptId)}`;
  }, []);

  // 共有モーダルのステータステキストをisErrorフラグと一緒に更新するヘルパー
  // Helper to update the share modal status text alongside the isError flag
  const setPromptShareStatus = useCallback((text: string, isError = false) => {
    setShareStatus({ text, isError });
  }, []);

  // キャッシュされた共有URLがあれば再利用し、なければ新たにURLを生成する
  // Reuses a cached share URL when available to avoid regenerating it unnecessarily
  const createPromptShareLink = useCallback(
    async (prompt: PromptRecord | null, forceRefresh = false) => {
      const promptId = getPromptId(prompt);
      if (!prompt || !promptId) {
        setShareUrl("");
        setPromptShareStatus("共有するプロンプトを選択してください。", true);
        return;
      }

      if (!forceRefresh && cachedPromptShareUrlsRef.current.has(promptId)) {
        setShareUrl(cachedPromptShareUrlsRef.current.get(promptId) || "");
        setPromptShareStatus("共有リンクを表示しています。");
        return;
      }

      setShareActionLoading(true);
      setPromptShareStatus("共有リンクを準備しています...");

      try {
        const generatedShareUrl = buildPromptShareUrl(prompt);
        cachedPromptShareUrlsRef.current.set(promptId, generatedShareUrl);
        setShareUrl(generatedShareUrl);
        setPromptShareStatus("共有リンクを表示しています。");
      } catch (error) {
        setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
      } finally {
        setShareActionLoading(false);
      }
    },
    [buildPromptShareUrl, setPromptShareStatus]
  );

  // 共有URLをクリップボードにコピーし、結果をステータスメッセージとして表示する
  // Copies the share URL to the clipboard and reflects the outcome in the status message
  const handleCopyShareLink = useCallback(async () => {
    const currentShareUrl = shareUrl.trim();
    if (!currentShareUrl) {
      setPromptShareStatus("先に共有リンクを表示してください。", true);
      return;
    }

    try {
      await copyTextToClipboard(currentShareUrl);
      setPromptShareStatus("リンクをコピーしました。");
    } catch (error) {
      setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  }, [setPromptShareStatus, shareUrl]);

  // Web Share APIを呼び出し、ネイティブ共有シートを表示する（非対応ブラウザでは使用不可）
  // Invokes the Web Share API to open the native share sheet (unavailable on unsupported browsers)
  const handleNativeShare = useCallback(async () => {
    const currentShareUrl = shareUrl.trim();
    if (!currentShareUrl) {
      setPromptShareStatus("先に共有リンクを表示してください。", true);
      return;
    }

    if (typeof navigator.share !== "function") {
      setPromptShareStatus("このブラウザはネイティブ共有に対応していません。", true);
      return;
    }

    try {
      await navigator.share({
        title: PROMPT_SHARE_TITLE,
        text: PROMPT_SHARE_TEXT,
        url: currentShareUrl
      });
      setPromptShareStatus("共有シートを開きました。");
    } catch (error) {
      // ユーザーが共有シートをキャンセルした場合はエラーとして扱わない
      // User-initiated cancellation of the share sheet is not treated as an error
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  }, [setPromptShareStatus, shareUrl]);

  // 指定プロンプトのコメントを取得する。モーダルの切り替えによる競合を防ぐためpromptIdで検証する
  // Fetches comments for a prompt; validates against the current promptId to prevent race conditions when switching modals
  const loadPromptComments = useCallback(
    async (promptId: string | number) => {
      const targetPromptId = String(promptId);
      detailPromptIdRef.current = targetPromptId;
      setIsDetailCommentsLoading(true);
      try {
        const payload = await fetchPromptComments(promptId);
        // 取得完了前にモーダルが切り替わっていた場合は結果を破棄する
        // Discard results if the modal was switched before the fetch completed
        if (detailPromptIdRef.current !== targetPromptId) {
          return;
        }
        const nextComments = Array.isArray(payload.comments) ? payload.comments : [];
        setDetailComments(nextComments);
        if (payload.comment_count !== undefined) {
          updatePromptCommentCount(promptId, payload.comment_count);
        }
      } catch (error) {
        if (detailPromptIdRef.current !== targetPromptId) {
          return;
        }
        console.error("コメント取得エラー:", error);
        showToast("コメントの読み込みに失敗しました。", { variant: "error" });
      } finally {
        if (detailPromptIdRef.current === targetPromptId) {
          setIsDetailCommentsLoading(false);
        }
      }
    },
    [updatePromptCommentCount]
  );

  // コメントを投稿し、成功したらレスポンスから直接コメントリストを更新する
  // Posts a comment and updates the comment list directly from the response to avoid a refetch
  const handleSubmitPromptComment = useCallback(async () => {
    if (!isLoggedIn) {
      showToast("コメントするにはログインが必要です。", { variant: "error" });
      return;
    }
    const promptId = getPromptId(detailPrompt);
    const content = commentDraft.trim();
    if (!promptId) {
      showToast("コメント対象のプロンプトが見つかりません。", { variant: "error" });
      return;
    }
    if (!content) {
      showToast("コメント内容を入力してください。", { variant: "error" });
      return;
    }
    setIsCommentSubmitting(true);
    try {
      const payload = await createPromptComment(promptId, content);
      if (payload.comment_count !== undefined) {
        updatePromptCommentCount(promptId, payload.comment_count);
      }
      if (payload.comment) {
        setDetailComments((current) => [...current, payload.comment!]);
      } else {
        // APIがコメントオブジェクトを返さなかった場合はコメント一覧を再取得する
        // If the API did not return a comment object, re-fetch the full comment list
        await loadPromptComments(promptId);
      }
      setCommentDraft("");
      showToast("コメントを投稿しました。", { variant: "success" });
    } catch (error) {
      console.error("コメント投稿エラー:", error);
      showToast(error instanceof Error ? error.message : "コメント投稿に失敗しました。", {
        variant: "error"
      });
    } finally {
      setIsCommentSubmitting(false);
    }
  }, [commentDraft, detailPrompt, isLoggedIn, loadPromptComments, updatePromptCommentCount]);

  // ユーザーに確認を求めてからコメントを削除し、削除後はリストから該当コメントを除外する
  // Prompts the user for confirmation before deleting, then removes the comment from the local list
  const handleDeletePromptComment = useCallback(
    async (commentId: string | number) => {
      const confirmed = await showConfirmModal("このコメントを削除しますか？");
      if (!confirmed) {
        return;
      }
      const commentKey = String(commentId);
      setCommentActionPending(commentKey, true);
      try {
        const payload = await deletePromptComment(commentId);
        setDetailComments((current) => current.filter((comment) => String(comment.id) !== commentKey));
        if (payload.prompt_id !== undefined && payload.comment_count !== undefined) {
          updatePromptCommentCount(payload.prompt_id, payload.comment_count);
        }
        showToast("コメントを削除しました。", { variant: "success" });
      } catch (error) {
        console.error("コメント削除エラー:", error);
        showToast(error instanceof Error ? error.message : "コメント削除に失敗しました。", {
          variant: "error"
        });
      } finally {
        setCommentActionPending(commentKey, false);
      }
    },
    [setCommentActionPending, updatePromptCommentCount]
  );

  // コメントを不正利用として報告し、モデレーターによって非表示にされた場合はリストから即座に除外する
  // Reports a comment for abuse and removes it from the local list immediately if the server hides it
  const handleReportPromptComment = useCallback(
    async (commentId: string | number) => {
      if (!isLoggedIn) {
        showToast("コメントを報告するにはログインが必要です。", { variant: "error" });
        return;
      }
      const confirmed = await showConfirmModal("このコメントを報告しますか？");
      if (!confirmed) {
        return;
      }
      const commentKey = String(commentId);
      setCommentActionPending(commentKey, true);
      try {
        const payload = await reportPromptComment(commentId, "abuse");
        if (payload.already_reported) {
          showToast("このコメントはすでに報告済みです。", { variant: "info" });
        } else {
          showToast("コメントを報告しました。", { variant: "success" });
        }
        if (payload.hidden) {
          setDetailComments((current) => current.filter((comment) => String(comment.id) !== commentKey));
        }
        if (payload.prompt_id !== undefined && payload.comment_count !== undefined) {
          updatePromptCommentCount(payload.prompt_id, payload.comment_count);
        }
      } catch (error) {
        console.error("コメント報告エラー:", error);
        showToast(error instanceof Error ? error.message : "コメント報告に失敗しました。", {
          variant: "error"
        });
      } finally {
        setCommentActionPending(commentKey, false);
      }
    },
    [isLoggedIn, setCommentActionPending, updatePromptCommentCount]
  );

  // 詳細モーダルからコメントを手動で再読み込みするためのアクション
  // Action for manually refreshing comments from within the detail modal
  const reloadDetailComments = useCallback(() => {
    const promptId = getPromptId(detailPrompt);
    if (!promptId) return;
    void loadPromptComments(promptId);
  }, [detailPrompt, loadPromptComments]);

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
      setCommentDraft("");
      setDetailComments([]);
      setCommentActionPendingIds(new Set());
      openModal("detail", promptDetailCloseButtonRef.current);
      if (promptId) {
        void loadPromptComments(promptId);
      }
    },
    [loadPromptComments, openModal]
  );

  // コメントビューで詳細モーダルを直接開き、テキストエリアへのフォーカスを優先する
  // Opens the detail modal directly in comments view, prioritizing focus on the textarea
  const openPromptCommentsModal = useCallback(
    (prompt: PromptRecord) => {
      const promptId = getPromptId(prompt);
      setOpenDropdownPromptId(null);
      setDetailModalView("comments");
      setDetailPrompt(prompt);
      setCommentDraft("");
      setDetailComments([]);
      setCommentActionPendingIds(new Set());
      openModal("detail", promptCommentTextareaRef.current || promptCommentsSectionRef.current);
      if (promptId) {
        void loadPromptComments(promptId);
      }
    },
    [loadPromptComments, openModal]
  );

  // 同じカードのドロップダウンを再度クリックした場合はトグルとして閉じる
  // Toggles the dropdown closed if the same card's menu is clicked again
  const togglePromptDropdown = useCallback((promptId: string) => {
    setOpenDropdownPromptId((current) => (current === promptId ? null : promptId));
  }, []);

  const closePromptDropdown = useCallback(() => {
    setOpenDropdownPromptId(null);
  }, []);

  // プロンプトのチャット利用状態をトグルするAPIを呼び出す。未ログインの場合はトーストで案内する
  // Calls the use-in-chat toggle API; shows a toast guide if the user is not logged in
  const handleAddPromptAsTask = useCallback(
    async (prompt: PromptRecord) => {
      const promptId = prompt.clientId;
      setOpenDropdownPromptId(null);

      if (!isLoggedIn) {
        showToast("チャットで使うにはログインが必要です。", { variant: "error" });
        return;
      }

      const wasUsedInChat = Boolean(prompt.used_in_chat);
      const nextUsedInChat = !wasUsedInChat;
      updatePromptRecord(promptId, (currentPrompt) => ({
        ...currentPrompt,
        used_in_chat: nextUsedInChat
      }));
      if (nextUsedInChat) {
        triggerActionEffect(`${promptId}:use-in-chat`);
      }

      setAddAsTaskPending(promptId, true);
      try {
        const response = nextUsedInChat
          ? await addPromptAsTask(prompt)
          : await removePromptAsTask(prompt);
        const serverMessage =
          typeof response.message === "string" && response.message.trim()
            ? response.message
            : "";
        const fallbackMessage = nextUsedInChat
          ? "チャットで使えるように追加しました。"
          : "チャットで使う設定を解除しました。";
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          used_in_chat: nextUsedInChat
        }));
        showToast(serverMessage || fallbackMessage, { variant: "success" });
      } catch (error) {
        console.error("チャット利用状態の更新中にエラーが発生しました:", error);
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          used_in_chat: wasUsedInChat
        }));
        showToast("チャットで使う設定の更新中にエラーが発生しました。", { variant: "error" });
      } finally {
        setAddAsTaskPending(promptId, false);
      }
    },
    [isLoggedIn, setAddAsTaskPending, triggerActionEffect, updatePromptRecord]
  );

  // いいね状態を楽観的UIで即座に反映し、API失敗時はロールバックする
  // Optimistically updates the like state immediately and rolls back if the API call fails
  const handleTogglePromptLike = useCallback(
    async (prompt: PromptRecord) => {
      if (!isLoggedIn) {
        showToast("いいねするにはログインが必要です。", { variant: "error" });
        return;
      }

      const promptId = prompt.clientId;
      // 処理中の場合は重複リクエストを無視する
      // Ignore duplicate requests while an operation is already in progress
      if (likePendingIdsRef.current.has(promptId)) {
        return;
      }

      const shouldLike = !prompt.liked;
      setLikePending(promptId, true);
      updatePromptRecord(promptId, (currentPrompt) => ({
        ...currentPrompt,
        liked: shouldLike
      }));
      if (shouldLike) {
        triggerActionEffect(`${promptId}:like`);
      }

      try {
        const request = shouldLike ? savePromptLike(prompt) : removePromptLike(prompt);
        await request;
      } catch (error) {
        console.error("いいね操作エラー:", error);
        // 失敗した場合は元の状態に戻す
        // Revert to the original state on failure
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          liked: !shouldLike
        }));
        showToast("いいねの更新中にエラーが発生しました。", { variant: "error" });
      } finally {
        setLikePending(promptId, false);
      }
    },
    [isLoggedIn, setLikePending, triggerActionEffect, updatePromptRecord]
  );

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
      const promptTypeToApply = selectedPromptTypeFilterRef.current;

      if (searchInput.trim()) {
        setSearchInput("");
        void loadPrompts({ categoryToApply: category, promptTypeToApply });
        return;
      }

      setAppliedCategoryFilter(category);
      setSelectedCategoryTitle(getCategoryTitle(category));

      setPromptCountMeta(buildPromptCountMeta(promptsRef.current, category, promptTypeToApply));
    },
    [buildPromptCountMeta, loadPrompts, searchInput]
  );

  // プロンプトタイプのフィルタをクリックしたとき、検索中なら再検索してフィルタを適用する
  // When a prompt type filter is clicked, re-searches if a query is active to apply the new filter
  const handlePromptTypeFilterClick = useCallback(
    (promptTypeFilter: PromptTypeFilter) => {
      setOpenDropdownPromptId(null);
      setSelectedPromptTypeFilter(promptTypeFilter);
      selectedPromptTypeFilterRef.current = promptTypeFilter;

      if (activeSearchQuery.trim() || searchInput.trim()) {
        void searchPrompts({ promptTypeToApply: promptTypeFilter });
        return;
      }

      setPromptCountMeta(
        buildPromptCountMeta(promptsRef.current, selectedCategoryRef.current, promptTypeFilter)
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

  // 画像ファイルが選択されたときにバリデーションを行い、問題なければプレビューを更新する
  // Validates the selected image file on change and updates the preview if validation passes
  const handleReferenceImageChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0] || null;
      const validationError = validateReferenceImageFile(file);
      if (validationError) {
        showToast(validationError, { variant: "error" });
        clearPromptImageSelection();
        return;
      }
      updatePromptImagePreview(file);
    },
    [clearPromptImageSelection, updatePromptImagePreview, validateReferenceImageFile]
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

      // プロンプトタイプに応じてフィールドを選択的にFormDataへ追加する
      // Selectively appends fields to FormData based on the selected prompt type
      const formData = new FormData();
      formData.append("title", postTitle);
      formData.append("category", postCategory === "未選択" ? "" : postCategory);
      formData.append("content", promptType === "skill" ? "" : postContent);
      formData.append("prompt_type", promptType);
      formData.append("input_examples", promptType !== "skill" && guardrailEnabled ? postInputExample : "");
      formData.append("output_examples", promptType !== "skill" && guardrailEnabled ? postOutputExample : "");
      formData.append("ai_model", postAiModel);
      formData.append("skill_markdown", promptType === "skill" ? postSkillMarkdown : "");
      formData.append("skill_python_script", promptType === "skill" ? postSkillPythonScript : "");

      if (promptType === "image" && referenceImageFile) {
        formData.append("reference_image", referenceImageFile);
      }

      setIsPostSubmitting(true);
      setPromptPostStatus("プロンプトを投稿しています...", "info");

      try {
        await createPrompt(formData);

        setPromptPostStatus("プロンプトが投稿されました。公開一覧へ反映します。", "success");

        // 投稿成功後にフォームを全フィールドリセットする
        // Reset all form fields after a successful submission
        setPromptType("text");
        setPostTitle("");
        setPostCategory("未選択");
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
          promptTypeToApply: selectedPromptTypeFilterRef.current
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
      promptType,
      referenceImageFile,
      setPromptPostStatus,
      validateReferenceImageFile
    ]
  );

  // ページ初期化時のセットアップ処理。カスタム要素を動的インポートしてWeb Shareの対応状況を検出する
  // Page initialization: dynamically imports custom elements and detects Web Share API support
  useEffect(() => {
    document.body.classList.add("prompt-share-page");
    setSupportsNativeShare(typeof navigator !== "undefined" && typeof navigator.share === "function");

    const importCustomElements = async () => {
      await Promise.all([
        import("../../scripts/components/popup_menu"),
        import("../../scripts/components/user_icon")
      ]);
    };
    void importCustomElements();

    return () => {
      // アンマウント時にスクロールロックとページ固有のクラスを全てクリーンアップする
      // Clean up scroll lock state and page-specific classes on unmount
      document.documentElement.classList.remove("ps-modal-open");
      document.body.classList.remove("ps-modal-open");
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.left = "";
      document.body.style.right = "";
      document.body.style.width = "";
      hasModalLockRef.current = false;
      document.body.classList.remove("prompt-share-page");

      if (postCloseTimerRef.current !== null) {
        window.clearTimeout(postCloseTimerRef.current);
        postCloseTimerRef.current = null;
      }
      revokePromptImagePreview();
    };
  }, [revokePromptImagePreview]);

  // キャッシュから即座にUIを表示し、バックグラウンドでAPIを呼び出して最新の認証状態を確認する
  // Shows the UI immediately from cache while checking the latest auth state from the API in the background
  useEffect(() => {
    const cachedAuthState = readCachedAuthState();
    if (cachedAuthState !== null) {
      setIsLoggedIn(cachedAuthState);
      setLoggedInState(cachedAuthState);
      setAuthUiReady(true);
    }

    let cancelled = false;
    // タイムアウト0でAPI呼び出しをマイクロタスクキューに遅延させ、キャッシュが先にレンダリングされるようにする
    // Defers the API call to the next tick so the cached state renders first
    const timerId = window.setTimeout(() => {
      void fetch("/api/current_user")
        .then((res) => (res.ok ? res.json() : { logged_in: false }))
        .then((data: { logged_in?: boolean }) => {
          if (cancelled) {
            return;
          }
          const loggedIn = Boolean(data.logged_in);
          setIsLoggedIn(loggedIn);
          setLoggedInState(loggedIn);
          setAuthUiReady(true);
          writeCachedAuthState(loggedIn);
        })
        .catch((error) => {
          if (cancelled) {
            return;
          }
          console.error("Error checking login status:", error);
          setIsLoggedIn(false);
          setLoggedInState(false);
          setAuthUiReady(true);
        });
    }, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
    };
  }, []);

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
      setPromptCountMeta(buildPromptCountMeta(promptRecords, "all", selectedPromptTypeFilterRef.current));
    }

    void loadPrompts();
  }, [buildPromptCountMeta, loadPrompts, toPromptRecords]);

  // 画像タイプ以外に切り替えた場合は参照画像の選択をクリアしてメモリを解放する
  // Clears the reference image selection to free memory when switching away from the image prompt type
  useEffect(() => {
    if (promptType !== "image") {
      clearPromptImageSelection();
    }
  }, [clearPromptImageSelection, promptType]);

  // プロンプトタイプが変わったときにAI補助パネルの表示を更新する
  // Updates the AI-assist panel display whenever the prompt type changes
  useEffect(() => {
    promptAssistControllerRef.current?.updateForPromptType(promptType);
  }, [promptType]);

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
          label: "投稿タイプ",
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

  // モーダルの開閉に応じてbodyのスクロールをロック/アンロックし、フォーカスを管理する
  // Locks/unlocks body scroll when modals open/close and manages focus accordingly
  useEffect(() => {
    if (!activeModal) {
      if (!hasModalLockRef.current) {
        previousFocusedElementRef.current = null;
        preferredFocusElementRef.current = null;
        return;
      }
      // モーダルを閉じるときにスクロール位置を復元する
      // Restore the scroll position when closing a modal
      document.documentElement.classList.remove("ps-modal-open");
      document.body.classList.remove("ps-modal-open");
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.left = "";
      document.body.style.right = "";
      document.body.style.width = "";
      window.scrollTo(0, lockedScrollYRef.current);
      hasModalLockRef.current = false;

      if (previousFocusedElementRef.current) {
        previousFocusedElementRef.current.focus();
      }
      previousFocusedElementRef.current = null;
      preferredFocusElementRef.current = null;
      return;
    }

    // position: fixed でbodyを固定し、CSSでスクロールバーが消えても幅が変わらないようにする
    // Fixes the body position to prevent scroll while keeping the width stable to avoid layout shift
    if (!document.body.classList.contains("ps-modal-open")) {
      lockedScrollYRef.current = window.scrollY || window.pageYOffset || 0;
      document.documentElement.classList.add("ps-modal-open");
      document.body.classList.add("ps-modal-open");
      document.body.style.position = "fixed";
      document.body.style.top = `-${lockedScrollYRef.current}px`;
      document.body.style.left = "0";
      document.body.style.right = "0";
      document.body.style.width = "100%";
      hasModalLockRef.current = true;
    }

    focusModal(activeModal);
  }, [activeModal, focusModal]);

  // モーダル内でのキーボード操作（Escape・Tabトラップ）を処理してアクセシビリティを確保する
  // Handles keyboard navigation inside modals (Escape to close, Tab trapping for accessibility)
  useEffect(() => {
    if (!activeModal) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      const modalElement = getModalElement(activeModal);
      if (!modalElement) {
        return;
      }

      if (event.key === "Escape") {
        // 投稿送信中はEscapeキーでモーダルを閉じない
        // Prevent closing the modal with Escape while a post submission is in progress
        if (activeModal === "post" && isPostSubmitting) {
          return;
        }
        event.preventDefault();
        closeModal(activeModal);
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      // Tabキーでフォーカスをモーダル内に閉じ込めるフォーカストラップ
      // Focus trap: keeps Tab navigation confined within the modal
      const focusableElements = getModalFocusableElements(modalElement);
      if (focusableElements.length === 0) {
        event.preventDefault();
        const fallback = modalElement.querySelector<HTMLElement>(".post-modal-content");
        fallback?.focus();
        return;
      }

      const firstFocusable = focusableElements[0];
      const lastFocusable = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;

      if (event.shiftKey) {
        if (!activeElement || activeElement === firstFocusable || !modalElement.contains(activeElement)) {
          event.preventDefault();
          lastFocusable.focus();
        }
        return;
      }

      if (!activeElement || activeElement === lastFocusable || !modalElement.contains(activeElement)) {
        event.preventDefault();
        firstFocusable.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [activeModal, closeModal, getModalElement, isPostSubmitting]);

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
      message: getFilterEmptyMessage(),
      variant: "empty"
    };
  }, [getFilterEmptyMessage, isPromptsLoading, promptFeedback, prompts.length, visiblePrompts.length]);

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
      >
        <link rel="stylesheet" href="/prompt_share/static/css/pages/prompt_share.css" />
      </SeoHead>

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
        promptTypeFilters={PROMPT_TYPE_FILTERS}
        selectedPromptTypeFilter={selectedPromptTypeFilter}
        onPromptTypeFilterClick={handlePromptTypeFilterClick}
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
          promptType={promptType}
          setPromptType={setPromptType}
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
          postSkillMarkdown={postSkillMarkdown}
          setPostSkillMarkdown={setPostSkillMarkdown}
          postSkillPythonScript={postSkillPythonScript}
          setPostSkillPythonScript={setPostSkillPythonScript}
          updatePromptFeedbackErrorIfNeeded={updatePromptFeedbackErrorIfNeeded}
          categoryOptions={PROMPT_CATEGORY_OPTIONS}
          promptPostStatus={promptPostStatus}
          promptPostTitleInputRef={promptPostTitleInputRef}
          promptPostCategorySelectRef={promptPostCategorySelectRef}
          promptPostContentTextareaRef={promptPostContentTextareaRef}
          promptPostAiModelSelectRef={promptPostAiModelSelectRef}
          promptPostInputExamplesRef={promptPostInputExamplesRef}
          promptPostOutputExamplesRef={promptPostOutputExamplesRef}
          promptPostSkillMarkdownRef={promptPostSkillMarkdownRef}
          promptPostSkillPythonScriptRef={promptPostSkillPythonScriptRef}
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
