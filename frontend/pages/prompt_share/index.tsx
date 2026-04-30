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

import { SeoHead } from "../../components/SeoHead";
import "../../scripts/core/csrf";
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
  removePromptBookmark,
  removePromptLike,
  savePromptBookmark,
  savePromptLike,
  savePromptToList
} from "../../scripts/prompt_share/api";
import {
  ACCEPTED_PROMPT_IMAGE_EXTENSIONS,
  ACCEPTED_PROMPT_IMAGE_TYPES,
  PROMPT_IMAGE_MAX_BYTES,
  PROMPT_SHARE_TEXT,
  PROMPT_SHARE_TITLE
} from "../../scripts/prompt_share/constants";
import { normalizePromptData } from "../../scripts/prompt_share/formatters";
import {
  readCachedAuthState,
  readPromptCache,
  writeCachedAuthState,
  writePromptCache
} from "../../scripts/prompt_share/storage";
import type {
  PromptCommentData,
  PromptData,
  PromptPagination,
  PromptType
} from "../../scripts/prompt_share/types";
import { PromptShareComposerModal } from "../../components/prompt_share/prompt_share_composer_modal";
import { PromptShareDetailModal } from "../../components/prompt_share/prompt_share_detail_modal";
import {
  PROMPT_CATEGORIES,
  PROMPT_CATEGORY_OPTIONS,
  SEARCH_RESULTS_PER_PAGE
} from "../../components/prompt_share/prompt_share_page_constants";
import { PromptSharePageLayout } from "../../components/prompt_share/prompt_share_page_layout";
import type {
  ModalKey,
  PromptFeedback,
  PromptPostStatus,
  PromptPostStatusVariant
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

const promptShareDescription =
  "Chat Coreのプロンプト共有ページです。文章作成、調査、画像生成などに使える日本語AIプロンプトを探して、保存して、共有できます。";

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

export default function PromptSharePage() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [authUiReady, setAuthUiReady] = useState(false);
  const [supportsNativeShare, setSupportsNativeShare] = useState(false);

  const [searchInput, setSearchInput] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [selectedCategoryTitle, setSelectedCategoryTitle] = useState("全てのプロンプト");
  const [appliedCategoryFilter, setAppliedCategoryFilter] = useState<string | null>("all");

  const [prompts, setPrompts] = useState<PromptRecord[]>([]);
  const [isPromptsLoading, setIsPromptsLoading] = useState(true);
  const [promptCountMeta, setPromptCountMeta] = useState("公開プロンプトを読み込み中...");
  const [promptFeedback, setPromptFeedback] = useState<PromptFeedback | null>(null);
  const [activeSearchQuery, setActiveSearchQuery] = useState("");
  const [searchPagination, setSearchPagination] = useState<PromptPagination | null>(null);
  const [isLoadingMoreSearchResults, setIsLoadingMoreSearchResults] = useState(false);

  const [activeModal, setActiveModal] = useState<ModalKey>(null);
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

  const [openDropdownPromptId, setOpenDropdownPromptId] = useState<string | null>(null);
  const [likePendingIds, setLikePendingIds] = useState<Set<string>>(new Set());
  const [bookmarkPendingIds, setBookmarkPendingIds] = useState<Set<string>>(new Set());
  const [saveToListPendingIds, setSaveToListPendingIds] = useState<Set<string>>(new Set());

  const [promptType, setPromptType] = useState<PromptType>("text");
  const [postTitle, setPostTitle] = useState("");
  const [postCategory, setPostCategory] = useState("未選択");
  const [postContent, setPostContent] = useState("");
  const [postAuthor, setPostAuthor] = useState("");
  const [postAiModel, setPostAiModel] = useState("");
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [postInputExample, setPostInputExample] = useState("");
  const [postOutputExample, setPostOutputExample] = useState("");
  const [referenceImageFile, setReferenceImageFile] = useState<File | null>(null);
  const [promptImagePreviewUrl, setPromptImagePreviewUrl] = useState("");
  const [promptImagePreviewName, setPromptImagePreviewName] = useState("");
  const [hasAutoFilledAuthor, setHasAutoFilledAuthor] = useState(false);
  const [isPostSubmitting, setIsPostSubmitting] = useState(false);
  const [promptPostStatus, setPromptPostStatusState] = useState<PromptPostStatus>({
    message: "",
    variant: "info"
  });

  const nextPromptClientIdRef = useRef(0);
  const promptsRef = useRef<PromptRecord[]>([]);
  const selectedCategoryRef = useRef("all");
  const hasAutoFilledAuthorRef = useRef(false);
  const activeModalRef = useRef<ModalKey>(null);

  const postModalRef = useRef<HTMLDivElement | null>(null);
  const promptDetailModalRef = useRef<HTMLDivElement | null>(null);
  const promptShareModalRef = useRef<HTMLDivElement | null>(null);

  const promptPostTitleInputRef = useRef<HTMLInputElement | null>(null);
  const promptPostCategorySelectRef = useRef<HTMLSelectElement | null>(null);
  const promptPostContentTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const promptPostAuthorInputRef = useRef<HTMLInputElement | null>(null);
  const promptPostAiModelSelectRef = useRef<HTMLSelectElement | null>(null);
  const promptPostInputExamplesRef = useRef<HTMLTextAreaElement | null>(null);
  const promptPostOutputExamplesRef = useRef<HTMLTextAreaElement | null>(null);

  const promptImageInputRef = useRef<HTMLInputElement | null>(null);

  const promptAssistRootRef = useRef<HTMLDivElement | null>(null);
  const promptAssistInitializedRef = useRef(false);
  const promptAssistControllerRef = useRef<{ reset: () => void } | null>(null);
  const promptTypeRef = useRef<PromptType>("text");

  const promptDetailCloseButtonRef = useRef<HTMLButtonElement | null>(null);
  const promptShareCopyButtonRef = useRef<HTMLButtonElement | null>(null);

  const previousFocusedElementRef = useRef<HTMLElement | null>(null);
  const preferredFocusElementRef = useRef<HTMLElement | null>(null);
  const lockedScrollYRef = useRef(0);
  const hasModalLockRef = useRef(false);

  const promptImagePreviewUrlRef = useRef("");
  const postCloseTimerRef = useRef<number | null>(null);
  const cachedPromptShareUrlsRef = useRef<Map<string, string>>(new Map());
  const detailPromptIdRef = useRef("");

  useEffect(() => {
    promptsRef.current = prompts;
  }, [prompts]);

  useEffect(() => {
    selectedCategoryRef.current = selectedCategory;
  }, [selectedCategory]);

  useEffect(() => {
    hasAutoFilledAuthorRef.current = hasAutoFilledAuthor;
  }, [hasAutoFilledAuthor]);

  useEffect(() => {
    activeModalRef.current = activeModal;
  }, [activeModal]);

  useEffect(() => {
    promptTypeRef.current = promptType;
  }, [promptType]);

  const toCachedPromptData = useCallback((items: PromptRecord[]) => {
    return items.map(({ clientId, ...prompt }) => prompt);
  }, []);

  const setPromptPostStatus = useCallback(
    (message: string, variant: PromptPostStatusVariant = "info") => {
      setPromptPostStatusState({ message, variant });
    },
    []
  );

  const updatePromptFeedbackErrorIfNeeded = useCallback(() => {
    setPromptPostStatusState((current) => {
      if (current.variant !== "error") {
        return current;
      }
      return { message: "", variant: "info" };
    });
  }, []);

  const revokePromptImagePreview = useCallback(() => {
    if (!promptImagePreviewUrlRef.current) {
      return;
    }
    URL.revokeObjectURL(promptImagePreviewUrlRef.current);
    promptImagePreviewUrlRef.current = "";
  }, []);

  const clearPromptImageSelection = useCallback(() => {
    revokePromptImagePreview();
    setReferenceImageFile(null);
    setPromptImagePreviewUrl("");
    setPromptImagePreviewName("");
    if (promptImageInputRef.current) {
      promptImageInputRef.current.value = "";
    }
  }, [revokePromptImagePreview]);

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

  const toPromptRecords = useCallback((items: PromptData[]) => {
    return items.map((item) => ({
      ...normalizePromptData(item),
      clientId: `prompt-${++nextPromptClientIdRef.current}`,
      liked: Boolean(item.liked)
    }));
  }, []);

  const countVisiblePrompts = useCallback((items: PromptRecord[], category: string | null) => {
    if (!category || category === "all") {
      return items.length;
    }
    return items.filter((item) => (item.category || "") === category).length;
  }, []);

  const visiblePrompts = useMemo(() => {
    if (!appliedCategoryFilter || appliedCategoryFilter === "all") {
      return prompts;
    }
    return prompts.filter((prompt) => (prompt.category || "") === appliedCategoryFilter);
  }, [prompts, appliedCategoryFilter]);
  const hasMoreSearchResults =
    activeSearchQuery.trim().length > 0 && Boolean(searchPagination?.has_next);

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

  const getModalElement = useCallback((modal: Exclude<ModalKey, null>) => {
    if (modal === "post") return postModalRef.current;
    if (modal === "detail") return promptDetailModalRef.current;
    return promptShareModalRef.current;
  }, []);

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

  const resetPostModalState = useCallback(() => {
    setPromptPostStatus("", "info");
    setIsPostSubmitting(false);
    promptAssistControllerRef.current?.reset();
  }, [setPromptPostStatus]);

  const closeModal = useCallback(
    (modal: Exclude<ModalKey, null>, options?: { rotateTrigger?: boolean }) => {
      if (activeModalRef.current !== modal) {
        return false;
      }

      setActiveModal(null);
      if (modal === "post") {
        resetPostModalState();
      } else if (modal === "detail") {
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


  const openModal = useCallback((modal: Exclude<ModalKey, null>, preferredElement?: HTMLElement | null) => {
    previousFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    preferredFocusElementRef.current = preferredElement || null;
    setActiveModal(modal);
  }, []);

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

  const setLikePending = useCallback((clientId: string, pending: boolean) => {
    setLikePendingIds((current) => {
      const next = new Set(current);
      if (pending) {
        next.add(clientId);
      } else {
        next.delete(clientId);
      }
      return next;
    });
  }, []);

  const setBookmarkPending = useCallback((clientId: string, pending: boolean) => {
    setBookmarkPendingIds((current) => {
      const next = new Set(current);
      if (pending) {
        next.add(clientId);
      } else {
        next.delete(clientId);
      }
      return next;
    });
  }, []);

  const setSaveToListPending = useCallback((clientId: string, pending: boolean) => {
    setSaveToListPendingIds((current) => {
      const next = new Set(current);
      if (pending) {
        next.add(clientId);
      } else {
        next.delete(clientId);
      }
      return next;
    });
  }, []);

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

  const loadPrompts = useCallback(
    async (options?: { categoryToApply?: string }) => {
      const categoryToApply = options?.categoryToApply || selectedCategoryRef.current;
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

        const visibleCount = countVisiblePrompts(promptRecords, categoryToApply);
        setPromptCountMeta(`${getCategoryCountLabel(categoryToApply)}: ${visibleCount}件`);
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
    [countVisiblePrompts, toPromptRecords]
  );

  const searchPrompts = useCallback(async () => {
    const query = searchInput.trim();

    if (!query) {
      setSelectedCategoryTitle("全てのプロンプト");
      await loadPrompts();
      return;
    }

    if (promptsRef.current.length === 0) {
      setIsPromptsLoading(true);
    }
    setSelectedCategoryTitle(`検索結果: 「${query}」`);

    try {
      const data = await fetchPromptSearchResults(query, {
        page: 1,
        perPage: SEARCH_RESULTS_PER_PAGE
      });
      const normalizedPrompts = Array.isArray(data.prompts)
        ? data.prompts.map(normalizePromptData)
        : [];
      const promptRecords = toPromptRecords(normalizedPrompts);

      setPrompts(promptRecords);
      setActiveSearchQuery(query);
      setSearchPagination(data.pagination || null);
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
        `検索結果: ${promptRecords.length}件 / ${Number(data.pagination?.total || promptRecords.length)}件`
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
  }, [loadPrompts, searchInput, toPromptRecords]);

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
        perPage: Number(searchPagination.per_page || SEARCH_RESULTS_PER_PAGE)
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
        `検索結果: ${nextPrompts.length}件 / ${Number(data.pagination?.total || nextPrompts.length)}件`
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
  }, [activeSearchQuery, searchPagination, toPromptRecords]);

  const buildPromptShareUrl = useCallback((prompt: PromptRecord | null) => {
    const promptId = getPromptId(prompt);
    if (!promptId) {
      throw new Error("共有対象のプロンプトIDが見つかりません。");
    }
    return `${window.location.origin}/shared/prompt/${encodeURIComponent(promptId)}`;
  }, []);

  const setPromptShareStatus = useCallback((text: string, isError = false) => {
    setShareStatus({ text, isError });
  }, []);

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
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  }, [setPromptShareStatus, shareUrl]);

  const applyDefaultAuthorName = useCallback((user?: { username?: string } | null) => {
    const username = String(user?.username || "").trim();
    if (!username) {
      return;
    }

    setPostAuthor((current) => {
      const currentValue = current.trim();
      const shouldAutofill =
        !currentValue || currentValue === "アイデア職人" || hasAutoFilledAuthorRef.current;
      if (!shouldAutofill) {
        return current;
      }
      setHasAutoFilledAuthor(true);
      return username;
    });
  }, []);

  const loadPromptComments = useCallback(
    async (promptId: string | number) => {
      const targetPromptId = String(promptId);
      detailPromptIdRef.current = targetPromptId;
      setIsDetailCommentsLoading(true);
      try {
        const payload = await fetchPromptComments(promptId);
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
        await loadPromptComments(promptId);
      }
      setCommentDraft("");
    } catch (error) {
      console.error("コメント投稿エラー:", error);
      showToast("コメント投稿に失敗しました。", { variant: "error" });
    } finally {
      setIsCommentSubmitting(false);
    }
  }, [commentDraft, detailPrompt, isLoggedIn, loadPromptComments, updatePromptCommentCount]);

  const handleDeletePromptComment = useCallback(
    async (commentId: string | number) => {
      const commentKey = String(commentId);
      setCommentActionPending(commentKey, true);
      try {
        const payload = await deletePromptComment(commentId);
        setDetailComments((current) => current.filter((comment) => String(comment.id) !== commentKey));
        if (payload.prompt_id !== undefined && payload.comment_count !== undefined) {
          updatePromptCommentCount(payload.prompt_id, payload.comment_count);
        }
      } catch (error) {
        console.error("コメント削除エラー:", error);
        showToast("コメント削除に失敗しました。", { variant: "error" });
      } finally {
        setCommentActionPending(commentKey, false);
      }
    },
    [setCommentActionPending, updatePromptCommentCount]
  );

  const handleReportPromptComment = useCallback(
    async (commentId: string | number) => {
      if (!isLoggedIn) {
        showToast("コメントを報告するにはログインが必要です。", { variant: "error" });
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
        showToast("コメント報告に失敗しました。", { variant: "error" });
      } finally {
        setCommentActionPending(commentKey, false);
      }
    },
    [isLoggedIn, setCommentActionPending, updatePromptCommentCount]
  );

  const reloadDetailComments = useCallback(() => {
    const promptId = getPromptId(detailPrompt);
    if (!promptId) return;
    void loadPromptComments(promptId);
  }, [detailPrompt, loadPromptComments]);

  const openPromptShareDialog = useCallback(
    (prompt: PromptRecord, event?: Event | MouseEvent<HTMLButtonElement>) => {
      event?.stopPropagation();
      setOpenDropdownPromptId(null);
      openModal("share", promptShareCopyButtonRef.current);
      void createPromptShareLink(prompt, false);
    },
    [createPromptShareLink, openModal]
  );

  const openPromptDetailModal = useCallback(
    (prompt: PromptRecord) => {
      const promptId = getPromptId(prompt);
      setOpenDropdownPromptId(null);
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

  const togglePromptDropdown = useCallback((promptId: string) => {
    setOpenDropdownPromptId((current) => (current === promptId ? null : promptId));
  }, []);

  const closePromptDropdown = useCallback(() => {
    setOpenDropdownPromptId(null);
  }, []);

  const handleSavePromptToList = useCallback(
    async (prompt: PromptRecord) => {
      const promptId = prompt.clientId;
      setOpenDropdownPromptId(null);

      if (!isLoggedIn) {
        showToast("プロンプトを保存するにはログインが必要です。", { variant: "error" });
        return;
      }

      if (prompt.saved_to_list) {
        showToast("このプロンプトはすでにプロンプトリストに保存されています。", { variant: "info" });
        return;
      }

      setSaveToListPending(promptId, true);
      try {
        await savePromptToList(prompt);
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          saved_to_list: true
        }));
      } catch (error) {
        console.error("プロンプト保存中にエラーが発生しました:", error);
        showToast("プロンプトリストへの保存中にエラーが発生しました。", { variant: "error" });
      } finally {
        setSaveToListPending(promptId, false);
      }
    },
    [isLoggedIn, setSaveToListPending, updatePromptRecord]
  );

  const handleTogglePromptLike = useCallback(
    async (prompt: PromptRecord) => {
      if (!isLoggedIn) {
        showToast("いいねするにはログインが必要です。", { variant: "error" });
        return;
      }

      const promptId = prompt.clientId;
      const shouldLike = !prompt.liked;
      setLikePending(promptId, true);
      try {
        const request = shouldLike ? savePromptLike(prompt) : removePromptLike(prompt);
        await request;

        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          liked: shouldLike
        }));
      } catch (error) {
        console.error("いいね操作エラー:", error);
        showToast("いいねの更新中にエラーが発生しました。", { variant: "error" });
      } finally {
        setLikePending(promptId, false);
      }
    },
    [isLoggedIn, setLikePending, updatePromptRecord]
  );

  const handleTogglePromptBookmark = useCallback(
    async (prompt: PromptRecord) => {
      if (!isLoggedIn) {
        showToast("ブックマークするにはログインが必要です。", { variant: "error" });
        return;
      }

      const promptId = prompt.clientId;
      const shouldBookmark = !prompt.bookmarked;
      setBookmarkPending(promptId, true);
      try {
        const request = shouldBookmark ? savePromptBookmark(prompt) : removePromptBookmark(prompt);
        await request;

        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          bookmarked: shouldBookmark
        }));
      } catch (error) {
        console.error("ブックマーク操作エラー:", error);
        showToast("ブックマークの更新中にエラーが発生しました。", { variant: "error" });
      } finally {
        setBookmarkPending(promptId, false);
      }
    },
    [isLoggedIn, setBookmarkPending, updatePromptRecord]
  );

  const openComposerModal = useCallback(() => {
    if (!isLoggedIn) {
      showToast("プロンプトを投稿するにはログインが必要です。", { variant: "error" });
      return;
    }

    setPromptPostStatus("カテゴリやタイトルを軽く入れてから AI 補助を使うと、提案が安定します。", "info");
    openModal("post", promptPostTitleInputRef.current);
  }, [isLoggedIn, openModal, setPromptPostStatus]);

  const handleCategoryClick = useCallback(
    (category: string) => {
      setOpenDropdownPromptId(null);
      setSelectedCategory(category);

      if (searchInput.trim()) {
        setSearchInput("");
        void loadPrompts({ categoryToApply: category });
        return;
      }

      setAppliedCategoryFilter(category);
      setSelectedCategoryTitle(getCategoryTitle(category));

      const visibleCount = countVisiblePrompts(promptsRef.current, category);
      setPromptCountMeta(`${getCategoryCountLabel(category)}: ${visibleCount}件`);
    },
    [countVisiblePrompts, loadPrompts, searchInput]
  );

  const handleSearchInputKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void searchPrompts();
      }
    },
    [searchPrompts]
  );

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

  const handlePostSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();

      if (
        !promptPostTitleInputRef.current ||
        !promptPostCategorySelectRef.current ||
        !promptPostContentTextareaRef.current ||
        !promptPostAuthorInputRef.current
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

      const formData = new FormData();
      formData.append("title", postTitle);
      formData.append("category", postCategory);
      formData.append("content", postContent);
      formData.append("author", postAuthor);
      formData.append("prompt_type", promptType);
      formData.append("input_examples", guardrailEnabled ? postInputExample : "");
      formData.append("output_examples", guardrailEnabled ? postOutputExample : "");
      formData.append("ai_model", postAiModel);

      if (promptType === "image" && referenceImageFile) {
        formData.append("reference_image", referenceImageFile);
      }

      setIsPostSubmitting(true);
      setPromptPostStatus("プロンプトを投稿しています...", "info");

      try {
        await createPrompt(formData);

        setPromptPostStatus("プロンプトが投稿されました。公開一覧へ反映します。", "success");

        setPromptType("text");
        setPostTitle("");
        setPostCategory("未選択");
        setPostContent("");
        setPostAuthor("");
        setPostAiModel("");
        setGuardrailEnabled(false);
        setPostInputExample("");
        setPostOutputExample("");
        clearPromptImageSelection();

        await loadPrompts();

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
      postAuthor,
      postCategory,
      postContent,
      postInputExample,
      postOutputExample,
      postTitle,
      promptType,
      referenceImageFile,
      setPromptPostStatus,
      validateReferenceImageFile
    ]
  );

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

  useEffect(() => {
    const cachedAuthState = readCachedAuthState();
    if (cachedAuthState !== null) {
      setIsLoggedIn(cachedAuthState);
      setLoggedInState(cachedAuthState);
      setAuthUiReady(true);
    }

    let cancelled = false;
    const timerId = window.setTimeout(() => {
      void fetch("/api/current_user")
        .then((res) => (res.ok ? res.json() : { logged_in: false }))
        .then((data: { logged_in?: boolean; user?: { username?: string } }) => {
          if (cancelled) {
            return;
          }
          const loggedIn = Boolean(data.logged_in);
          setIsLoggedIn(loggedIn);
          setLoggedInState(loggedIn);
          setAuthUiReady(true);
          writeCachedAuthState(loggedIn);
          if (loggedIn) {
            applyDefaultAuthorName(data.user);
          }
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
  }, [applyDefaultAuthorName]);

  useEffect(() => {
    const cachedPrompts = readPromptCache();
    if (cachedPrompts && cachedPrompts.length > 0) {
      const normalizedCache = cachedPrompts.map(normalizePromptData);
      const promptRecords = toPromptRecords(normalizedCache);
      setPrompts(promptRecords);
      setPromptFeedback(null);
      setIsPromptsLoading(false);
      const visibleCount = countVisiblePrompts(promptRecords, "all");
      setPromptCountMeta(`${getCategoryCountLabel("all")}: ${visibleCount}件`);
    }

    void loadPrompts();
  }, [countVisiblePrompts, loadPrompts, toPromptRecords]);

  useEffect(() => {
    if (promptType !== "image") {
      clearPromptImageSelection();
    }
  }, [clearPromptImageSelection, promptType]);

  useEffect(() => {
    const handleDocumentClick = () => {
      setOpenDropdownPromptId(null);
    };
    document.addEventListener("click", handleDocumentClick);
    return () => {
      document.removeEventListener("click", handleDocumentClick);
    };
  }, []);

  useEffect(() => {
    if (!promptAssistRootRef.current || promptAssistInitializedRef.current) {
      return;
    }
    if (
      !promptPostTitleInputRef.current ||
      !promptPostCategorySelectRef.current ||
      !promptPostContentTextareaRef.current ||
      !promptPostAuthorInputRef.current ||
      !promptPostAiModelSelectRef.current ||
      !promptPostInputExamplesRef.current ||
      !promptPostOutputExamplesRef.current
    ) {
      return;
    }

    const controller = initPromptAssist({
      root: promptAssistRootRef.current,
      target: "shared_prompt_modal",
      fields: {
        title: { label: "タイトル", element: promptPostTitleInputRef.current },
        category: { label: "カテゴリ", element: promptPostCategorySelectRef.current },
        content: { label: "プロンプト内容", element: promptPostContentTextareaRef.current },
        author: { label: "投稿者名", element: promptPostAuthorInputRef.current },
        ai_model: { label: "使用AIモデル", element: promptPostAiModelSelectRef.current },
        prompt_type: {
          label: "投稿タイプ",
          element: null,
          getValue: () => promptTypeRef.current
        },
        input_examples: { label: "入力例", element: promptPostInputExamplesRef.current },
        output_examples: { label: "出力例", element: promptPostOutputExamplesRef.current }
      },
      beforeApplyField: (fieldName) => {
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

  useEffect(() => {
    if (!activeModal) {
      if (!hasModalLockRef.current) {
        previousFocusedElementRef.current = null;
        preferredFocusElementRef.current = null;
        return;
      }
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

  const showPromptFeedback = Boolean(promptFeedback && visiblePrompts.length === 0 && !isPromptsLoading);
  const feedbackToShow = showPromptFeedback ? promptFeedback : null;

  return (
    <>
      <SeoHead
        title="プロンプト共有 | Chat Core"
        description={promptShareDescription}
        canonicalPath="/prompt_share"
        structuredData={promptShareStructuredData}
      >
        <link rel="stylesheet" href="/prompt_share/static/css/pages/prompt_share.css" />
      </SeoHead>

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
        bookmarkPendingIds={bookmarkPendingIds}
        saveToListPendingIds={saveToListPendingIds}
        onOpenDetail={openPromptDetailModal}
        onOpenShare={openPromptShareDialog}
        onToggleDropdown={togglePromptDropdown}
        onCloseDropdown={closePromptDropdown}
        onSaveToList={handleSavePromptToList}
        onToggleLike={handleTogglePromptLike}
        onToggleBookmark={handleTogglePromptBookmark}
      >

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
          postAuthor={postAuthor}
          setPostAuthor={setPostAuthor}
          setHasAutoFilledAuthor={setHasAutoFilledAuthor}
          postAiModel={postAiModel}
          setPostAiModel={setPostAiModel}
          guardrailEnabled={guardrailEnabled}
          setGuardrailEnabled={setGuardrailEnabled}
          postInputExample={postInputExample}
          setPostInputExample={setPostInputExample}
          postOutputExample={postOutputExample}
          setPostOutputExample={setPostOutputExample}
          updatePromptFeedbackErrorIfNeeded={updatePromptFeedbackErrorIfNeeded}
          categoryOptions={PROMPT_CATEGORY_OPTIONS}
          promptPostStatus={promptPostStatus}
          promptPostTitleInputRef={promptPostTitleInputRef}
          promptPostCategorySelectRef={promptPostCategorySelectRef}
          promptPostContentTextareaRef={promptPostContentTextareaRef}
          promptPostAuthorInputRef={promptPostAuthorInputRef}
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

        <PromptShareDetailModal
          isOpen={activeModal === "detail"}
          isLoggedIn={isLoggedIn}
          promptDetailModalRef={promptDetailModalRef}
          detailPrompt={detailPrompt}
          detailComments={detailComments}
          isDetailCommentsLoading={isDetailCommentsLoading}
          isCommentSubmitting={isCommentSubmitting}
          commentDraft={commentDraft}
          commentActionPendingIds={commentActionPendingIds}
          promptDetailCloseButtonRef={promptDetailCloseButtonRef}
          onCommentDraftChange={setCommentDraft}
          onSubmitComment={handleSubmitPromptComment}
          onDeleteComment={handleDeletePromptComment}
          onReportComment={handleReportPromptComment}
          onReloadComments={reloadDetailComments}
          onClose={() => {
            closeModal("detail");
          }}
        />

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
