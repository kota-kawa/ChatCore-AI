import Head from "next/head";
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

import "../../scripts/core/csrf";
import { copyTextToClipboard } from "../../scripts/chat/message_utils";
import { initPromptAssist } from "../../scripts/components/prompt_assist";
import { setLoggedInState } from "../../scripts/core/app_state";
import {
  createPrompt,
  fetchPromptList,
  fetchPromptSearchResults,
  removePromptBookmark,
  savePromptBookmark,
  savePromptToList
} from "../../scripts/prompt_share/api";
import {
  ACCEPTED_PROMPT_IMAGE_EXTENSIONS,
  ACCEPTED_PROMPT_IMAGE_TYPES,
  PROMPT_IMAGE_MAX_BYTES,
  PROMPT_SHARE_TEXT,
  PROMPT_SHARE_TITLE
} from "../../scripts/prompt_share/constants";
import {
  formatPromptDate,
  getPromptTypeIconClass,
  getPromptTypeLabel,
  normalizePromptData,
  normalizePromptType,
  truncateContent,
  truncateTitle
} from "../../scripts/prompt_share/formatters";
import {
  readCachedAuthState,
  readPromptCache,
  writeCachedAuthState,
  writePromptCache
} from "../../scripts/prompt_share/storage";
import type { PromptData, PromptType } from "../../scripts/prompt_share/types";

type PromptCategory = {
  value: string;
  iconClass: string;
  label: string;
};

type PromptRecord = PromptData & {
  clientId: string;
  liked: boolean;
};

type ModalKey = "post" | "detail" | "share" | null;

type PromptFeedback = {
  message: string;
  variant: "empty" | "error";
};

type PromptPostStatusVariant = "info" | "success" | "error";

type PromptPostStatus = {
  message: string;
  variant: PromptPostStatusVariant;
};

const PROMPT_CATEGORIES: PromptCategory[] = [
  { value: "all", iconClass: "bi bi-grid", label: "全て" },
  { value: "恋愛", iconClass: "bi bi-heart-fill", label: "恋愛" },
  { value: "勉強", iconClass: "bi bi-book", label: "勉強" },
  { value: "趣味", iconClass: "bi bi-camera", label: "趣味" },
  { value: "仕事", iconClass: "bi bi-briefcase", label: "仕事" },
  { value: "その他", iconClass: "bi bi-stars", label: "その他" },
  { value: "スポーツ", iconClass: "bi bi-trophy", label: "スポーツ" },
  { value: "音楽", iconClass: "bi bi-music-note", label: "音楽" },
  { value: "旅行", iconClass: "bi bi-geo-alt", label: "旅行" },
  { value: "グルメ", iconClass: "bi bi-shop", label: "グルメ" }
];

const PROMPT_CATEGORY_OPTIONS = [
  "未選択",
  "恋愛",
  "勉強",
  "趣味",
  "仕事",
  "その他",
  "スポーツ",
  "音楽",
  "旅行",
  "グルメ"
];

function getCategoryCountLabel(category: string) {
  return category === "all" ? "公開プロンプト" : category;
}

function getCategoryTitle(category: string) {
  return category === "all" ? "全てのプロンプト" : `${category} のプロンプト`;
}

function getPromptId(prompt: PromptData | null | undefined) {
  if (!prompt) return "";
  if (prompt.id === undefined || prompt.id === null) return "";
  return String(prompt.id);
}

function getModalFocusableElements(modal: HTMLElement) {
  const selector = [
    "a[href]",
    "area[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])"
  ].join(", ");

  return Array.from(modal.querySelectorAll<HTMLElement>(selector)).filter((element) => {
    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  });
}

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

  const [activeModal, setActiveModal] = useState<ModalKey>(null);
  const [detailPrompt, setDetailPrompt] = useState<PromptRecord | null>(null);
  const [shareUrl, setShareUrl] = useState("");
  const [shareStatus, setShareStatus] = useState({
    text: "共有するプロンプトを選択してください。",
    isError: false
  });
  const [shareActionLoading, setShareActionLoading] = useState(false);

  const [openDropdownPromptId, setOpenDropdownPromptId] = useState<string | null>(null);
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
  const promptNewButtonIconRef = useRef<HTMLElement | null>(null);

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
      liked: false
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

  const triggerNewPromptIconRotation = useCallback(() => {
    const icon = promptNewButtonIconRef.current;
    if (!icon) return;
    icon.classList.remove("rotating");
    void icon.offsetWidth;
    icon.classList.add("rotating");
  }, []);

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
        if (options?.rotateTrigger) {
          triggerNewPromptIconRotation();
        }
      }
      return true;
    },
    [resetPostModalState, triggerNewPromptIconRotation]
  );

  const openModal = useCallback((modal: Exclude<ModalKey, null>, preferredElement?: HTMLElement | null) => {
    previousFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    preferredFocusElementRef.current = preferredElement || null;
    setActiveModal(modal);
  }, []);

  const updatePromptRecord = useCallback(
    (clientId: string, updater: (prompt: PromptRecord) => PromptRecord) => {
      setPrompts((current) =>
        current.map((prompt) => (prompt.clientId === clientId ? updater(prompt) : prompt))
      );
    },
    []
  );

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
      const data = await fetchPromptSearchResults(query);
      const normalizedPrompts = Array.isArray(data.prompts)
        ? data.prompts.map(normalizePromptData)
        : [];
      const promptRecords = toPromptRecords(normalizedPrompts);

      setPrompts(promptRecords);
      setAppliedCategoryFilter(null);

      if (promptRecords.length > 0) {
        setPromptFeedback(null);
      } else {
        setPromptFeedback({
          message: "該当するプロンプトが見つかりませんでした。",
          variant: "empty"
        });
      }
      setPromptCountMeta(`検索結果: ${promptRecords.length}件`);
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
      setOpenDropdownPromptId(null);
      setDetailPrompt(prompt);
      openModal("detail", promptDetailCloseButtonRef.current);
    },
    [openModal]
  );

  const openComposerModal = useCallback(() => {
    if (!isLoggedIn) {
      alert("プロンプトを投稿するにはログインが必要です。");
      return;
    }

    triggerNewPromptIconRotation();
    setPromptPostStatus("カテゴリやタイトルを軽く入れてから AI 補助を使うと、提案が安定します。", "info");
    openModal("post", promptPostTitleInputRef.current);
  }, [isLoggedIn, openModal, setPromptPostStatus, triggerNewPromptIconRotation]);

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
        alert(validationError);
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
        const result = await createPrompt(formData);
        if (result.message) {
          console.log(result.message);
        }

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
    const icon = promptNewButtonIconRef.current;
    if (!icon) {
      return;
    }
    const handleAnimationEnd = () => {
      icon.classList.remove("rotating");
    };
    icon.addEventListener("animationend", handleAnimationEnd);
    return () => {
      icon.removeEventListener("animationend", handleAnimationEnd);
    };
  }, []);

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
      const activeElement = document.activeElement as HTMLElement | null;

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
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>プロンプト共有 - トップ</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link rel="dns-prefetch" href="https://cdn.jsdelivr.net" />
        <link rel="preconnect" href="https://cdn.jsdelivr.net" crossOrigin="anonymous" />
      </Head>

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
                    setSearchInput(event.target.value);
                  }}
                  onKeyDown={handleSearchInputKeyDown}
                />
                <button
                  id="searchButton"
                  type="button"
                  aria-label="検索を実行する"
                  data-tooltip="入力したキーワードで検索"
                  data-tooltip-placement="bottom"
                  onClick={() => {
                    void searchPrompts();
                  }}
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
                onClick={openComposerModal}
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
              {PROMPT_CATEGORIES.map((category) => (
                <button
                  key={category.value}
                  type="button"
                  className={`category-card${selectedCategory === category.value ? " active" : ""}`}
                  data-category={category.value}
                  onClick={() => {
                    handleCategoryClick(category.value);
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
            </div>

            <div id="promptResults"></div>

            <div className="prompt-cards">
              {isPromptsLoading && visiblePrompts.length === 0 && !promptFeedback ? (
                <p className="prompt-loading-message">読み込み中...</p>
              ) : null}

              {feedbackToShow ? (
                <p className={`prompt-feedback prompt-feedback--${feedbackToShow.variant}`}>
                  {feedbackToShow.message}
                </p>
              ) : null}

              {visiblePrompts.map((prompt) => {
                const promptTypeValue = normalizePromptType(prompt.prompt_type);
                const isBookmarked = Boolean(prompt.bookmarked);
                const isSavedToList = Boolean(prompt.saved_to_list);
                const promptId = prompt.clientId;
                const isBookmarkPending = bookmarkPendingIds.has(promptId);
                const isSaveToListPending = saveToListPendingIds.has(promptId);
                const isDropdownOpen = openDropdownPromptId === promptId;
                const safeCategory = prompt.category || "未分類";
                const safeCreatedAt = formatPromptDate(prompt.created_at) || "日付未設定";

                return (
                  <div
                    key={prompt.clientId}
                    className={`prompt-card${isDropdownOpen ? " menu-open" : ""}`}
                    data-category={prompt.category || ""}
                    onClick={() => {
                      openPromptDetailModal(prompt);
                    }}
                  >
                    <div className="prompt-card__header">
                      <div className="prompt-card__badges">
                        <span className="prompt-card__category-pill">
                          <i className="bi bi-hash"></i>
                          <span>{safeCategory}</span>
                        </span>
                        <span className={`prompt-card__type-pill prompt-card__type-pill--${promptTypeValue}`}>
                          <i className={`bi ${getPromptTypeIconClass(promptTypeValue)}`}></i>
                          <span>{getPromptTypeLabel(promptTypeValue)}</span>
                        </span>
                      </div>
                      <span className="prompt-card__created-at">
                        <i className="bi bi-calendar3"></i>
                        {safeCreatedAt}
                      </span>
                      <button
                        className="meatball-menu"
                        type="button"
                        aria-label="その他の操作"
                        aria-haspopup="true"
                        aria-expanded={isDropdownOpen ? "true" : "false"}
                        data-tooltip="その他の操作"
                        data-tooltip-placement="left"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenDropdownPromptId((current) =>
                            current === promptId ? null : promptId
                          );
                        }}
                      >
                        <i className="bi bi-three-dots"></i>
                      </button>
                    </div>

                    <div
                      className={`prompt-actions-dropdown${isDropdownOpen ? " is-open" : ""}`}
                      role="menu"
                      onClick={(event) => {
                        event.stopPropagation();
                      }}
                    >
                      <button
                        className="dropdown-item"
                        type="button"
                        role="menuitem"
                        data-action="share"
                        onClick={(event) => {
                          openPromptShareDialog(prompt, event);
                          setOpenDropdownPromptId(null);
                        }}
                      >
                        共有する
                      </button>
                      <button
                        className="dropdown-item"
                        type="button"
                        role="menuitem"
                        data-action="save-to-list"
                        disabled={isSavedToList || isSaveToListPending}
                        onClick={async (event) => {
                          event.stopPropagation();
                          setOpenDropdownPromptId(null);

                          if (!isLoggedIn) {
                            alert("プロンプトを保存するにはログインが必要です。");
                            return;
                          }

                          if (isSavedToList) {
                            alert("このプロンプトはすでにプロンプトリストに保存されています。");
                            return;
                          }

                          setSaveToListPending(promptId, true);
                          try {
                            const result = await savePromptToList(prompt);
                            updatePromptRecord(promptId, (currentPrompt) => ({
                              ...currentPrompt,
                              saved_to_list: true
                            }));
                            if (result && result.message) {
                              console.log(result.message);
                            }
                          } catch (error) {
                            console.error("プロンプト保存中にエラーが発生しました:", error);
                            alert("プロンプトリストへの保存中にエラーが発生しました。");
                          } finally {
                            setSaveToListPending(promptId, false);
                          }
                        }}
                      >
                        {isSavedToList ? "プロンプトリストに保存済み" : "プロンプトリストに保存"}
                      </button>
                      <button
                        className="dropdown-item"
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setOpenDropdownPromptId(null);
                        }}
                      >
                        ミュート
                      </button>
                      <button
                        className="dropdown-item"
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setOpenDropdownPromptId(null);
                        }}
                      >
                        報告する
                      </button>
                    </div>

                    {prompt.reference_image_url ? (
                      <div className="prompt-card__image">
                        <img
                          src={prompt.reference_image_url}
                          alt={`${truncateTitle(prompt.title)} の作例画像`}
                          loading="lazy"
                          decoding="async"
                        />
                      </div>
                    ) : null}

                    <h3>{truncateTitle(prompt.title)}</h3>
                    <p className="prompt-card__content">{truncateContent(prompt.content)}</p>

                    <div className="prompt-meta">
                      <div className="prompt-actions">
                        <button
                          className="prompt-action-btn comment-btn"
                          type="button"
                          aria-label="コメント"
                          data-tooltip="コメント（準備中）"
                          data-tooltip-placement="top"
                          onClick={(event) => {
                            event.stopPropagation();
                          }}
                        >
                          <i className="bi bi-chat-dots"></i>
                        </button>
                        <button
                          className={`prompt-action-btn like-btn${prompt.liked ? " liked" : ""}`}
                          type="button"
                          aria-label="いいね"
                          aria-pressed={prompt.liked ? "true" : "false"}
                          data-tooltip="このプロンプトにいいね"
                          data-tooltip-placement="top"
                          onClick={(event) => {
                            event.stopPropagation();
                            updatePromptRecord(promptId, (currentPrompt) => ({
                              ...currentPrompt,
                              liked: !currentPrompt.liked
                            }));
                          }}
                        >
                          <i className={`bi ${prompt.liked ? "bi-heart-fill" : "bi-heart"}`}></i>
                        </button>
                        <button
                          className={`prompt-action-btn bookmark-btn${isBookmarked ? " bookmarked" : ""}`}
                          type="button"
                          aria-label="保存"
                          aria-pressed={isBookmarked ? "true" : "false"}
                          data-tooltip={isBookmarked ? "保存を解除" : "このプロンプトを保存"}
                          data-tooltip-placement="top"
                          disabled={isBookmarkPending}
                          onClick={async (event) => {
                            event.stopPropagation();
                            if (!isLoggedIn) {
                              alert("ブックマークするにはログインが必要です。");
                              return;
                            }

                            const shouldBookmark = !isBookmarked;
                            setBookmarkPending(promptId, true);
                            try {
                              const request = shouldBookmark
                                ? savePromptBookmark(prompt)
                                : removePromptBookmark(prompt);
                              const result = await request;

                              updatePromptRecord(promptId, (currentPrompt) => ({
                                ...currentPrompt,
                                bookmarked: shouldBookmark
                              }));

                              if (result && result.message) {
                                console.log(result.message);
                              }
                            } catch (error) {
                              console.error("ブックマーク操作エラー:", error);
                              alert("ブックマークの更新中にエラーが発生しました。");
                            } finally {
                              setBookmarkPending(promptId, false);
                            }
                          }}
                        >
                          <i className={`bi ${isBookmarked ? "bi-bookmark-check-fill" : "bi-bookmark"}`}></i>
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </main>

        <div
          id="postModal"
          className={`post-modal${activeModal === "post" ? " show" : ""}`}
          role="dialog"
          aria-modal="true"
          aria-labelledby="postModalTitle"
          aria-hidden={activeModal === "post" ? "false" : "true"}
          data-submitting={isPostSubmitting ? "true" : "false"}
          ref={postModalRef}
        >
          <div className="post-modal-content post-modal-content--composer" tabIndex={-1}>
            <button
              type="button"
              className="close-btn"
              aria-label="投稿モーダルを閉じる"
              onClick={() => {
                closeModal("post", { rotateTrigger: true });
              }}
            >
              &times;
            </button>

            <div className="post-modal-scroll">
              <div className="composer-hero">
                <div className="composer-hero__copy">
                  <p className="composer-hero__eyebrow">Prompt Share Composer</p>
                  <h2 id="postModalTitle">新しいプロンプトを投稿</h2>
                  <p className="post-modal-lead">
                    AI 補助を使いながら、公開用の見やすさと使いやすさまでその場で仕上げます。
                  </p>
                </div>
                <div className="composer-hero__chips" aria-hidden="true">
                  <span>Searchable</span>
                  <span>Polished</span>
                  <span>Share Ready</span>
                </div>
              </div>

              <form className="post-form" id="postForm" onSubmit={handlePostSubmit}>
                <div className="form-group">
                  <label>投稿タイプ</label>
                  <div className="prompt-type-toggle" role="radiogroup" aria-label="投稿タイプを選択">
                    <label className={`prompt-type-option${promptType === "text" ? " prompt-type-option--active" : ""}`}>
                      <input
                        type="radio"
                        name="prompt-type"
                        value="text"
                        checked={promptType === "text"}
                        onChange={(event) => {
                          setPromptType(normalizePromptType(event.target.value));
                        }}
                      />
                      <span className="prompt-type-option__icon">
                        <i className="bi bi-chat-square-text"></i>
                      </span>
                      <span className="prompt-type-option__body">
                        <strong>通常プロンプト</strong>
                        <small>文章生成、要約、相談、分析など</small>
                      </span>
                    </label>

                    <label className={`prompt-type-option${promptType === "image" ? " prompt-type-option--active" : ""}`}>
                      <input
                        type="radio"
                        name="prompt-type"
                        value="image"
                        checked={promptType === "image"}
                        onChange={(event) => {
                          setPromptType(normalizePromptType(event.target.value));
                        }}
                      />
                      <span className="prompt-type-option__icon">
                        <i className="bi bi-image"></i>
                      </span>
                      <span className="prompt-type-option__body">
                        <strong>画像生成プロンプト</strong>
                        <small>Midjourney、Stable Diffusion、Flux など向け</small>
                      </span>
                    </label>
                  </div>
                </div>

                <div className="form-group">
                  <label htmlFor="prompt-title">タイトル</label>
                  <input
                    type="text"
                    id="prompt-title"
                    placeholder="プロンプトのタイトルを入力"
                    required
                    ref={promptPostTitleInputRef}
                    value={postTitle}
                    onChange={(event) => {
                      setPostTitle(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="prompt-category">カテゴリ</label>
                  <select
                    id="prompt-category"
                    required
                    ref={promptPostCategorySelectRef}
                    value={postCategory}
                    onChange={(event) => {
                      setPostCategory(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  >
                    {PROMPT_CATEGORY_OPTIONS.map((category) => (
                      <option key={category} value={category}>
                        {category}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label htmlFor="prompt-content">プロンプト内容</label>
                  <textarea
                    id="prompt-content"
                    rows={5}
                    placeholder="具体的なプロンプト内容を入力"
                    required
                    ref={promptPostContentTextareaRef}
                    value={postContent}
                    onChange={(event) => {
                      setPostContent(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  ></textarea>
                </div>

                <div id="sharedPromptAssistRoot" ref={promptAssistRootRef}></div>
                <p
                  id="promptPostStatus"
                  className="composer-status"
                  hidden={!promptPostStatus.message}
                  data-variant={promptPostStatus.variant}
                >
                  {promptPostStatus.message}
                </p>

                <div className="form-group">
                  <label htmlFor="prompt-author">投稿者名</label>
                  <input
                    type="text"
                    id="prompt-author"
                    placeholder="ニックネームなど"
                    required
                    ref={promptPostAuthorInputRef}
                    value={postAuthor}
                    onChange={(event) => {
                      setPostAuthor(event.target.value);
                      setHasAutoFilledAuthor(false);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="prompt-ai-model">使用AIモデル（任意）</label>
                  <select
                    id="prompt-ai-model"
                    ref={promptPostAiModelSelectRef}
                    value={postAiModel}
                    onChange={(event) => {
                      setPostAiModel(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  >
                    <option value="">未設定</option>
                    <optgroup label="OpenAI">
                      <option value="ChatGPT (GPT-5.4)">ChatGPT (GPT-5.4)</option>
                      <option value="ChatGPT (GPT-5.4 mini)">ChatGPT (GPT-5.4 mini)</option>
                      <option value="ChatGPT (o3)">ChatGPT (o3)</option>
                      <option value="ChatGPT (GPT-4o)">ChatGPT (GPT-4o)</option>
                    </optgroup>
                    <optgroup label="Anthropic">
                      <option value="Claude Opus 4.6">Claude Opus 4.6</option>
                      <option value="Claude Sonnet 4.6">Claude Sonnet 4.6</option>
                      <option value="Claude Haiku 4.5">Claude Haiku 4.5</option>
                      <option value="Claude 3.7 Sonnet">Claude 3.7 Sonnet</option>
                    </optgroup>
                    <optgroup label="Google">
                      <option value="Gemini 3.1 Pro">Gemini 3.1 Pro</option>
                      <option value="Gemini 3.1 Flash">Gemini 3.1 Flash</option>
                      <option value="Gemini 2.0 Flash">Gemini 2.0 Flash</option>
                    </optgroup>
                    <optgroup label="Meta">
                      <option value="Llama 4 Maverick">Llama 4 Maverick</option>
                      <option value="Llama 4 Scout">Llama 4 Scout</option>
                    </optgroup>
                    <optgroup label="DeepSeek">
                      <option value="DeepSeek-R1">DeepSeek-R1</option>
                      <option value="DeepSeek-V3">DeepSeek-V3</option>
                    </optgroup>
                    <optgroup label="xAI">
                      <option value="Grok 3">Grok 3</option>
                    </optgroup>
                    <optgroup label="画像生成">
                      <option value="Midjourney">Midjourney</option>
                      <option value="Stable Diffusion">Stable Diffusion</option>
                      <option value="FLUX">FLUX</option>
                      <option value="DALL-E 3">DALL-E 3</option>
                    </optgroup>
                    <option value="その他">その他</option>
                  </select>
                </div>

                <div id="imagePromptFields" className="image-prompt-fields" hidden={promptType !== "image"}>
                  <div className="form-group">
                    <label htmlFor="prompt-reference-image">作例画像（任意・1枚）</label>
                    <label className="image-upload-field" htmlFor="prompt-reference-image">
                      <input
                        type="file"
                        id="prompt-reference-image"
                        accept="image/png,image/jpeg,image/webp,image/gif"
                        ref={promptImageInputRef}
                        onChange={handleReferenceImageChange}
                      />
                      <span className="image-upload-field__icon">
                        <i className="bi bi-cloud-arrow-up"></i>
                      </span>
                      <span className="image-upload-field__copy">
                        <strong>画像をアップロード</strong>
                        <small>PNG / JPG / WebP / GIF、5MBまで、1枚のみ</small>
                      </span>
                    </label>

                    <div id="promptImagePreview" className="prompt-image-preview" hidden={!promptImagePreviewUrl}>
                      <img id="promptImagePreviewImg" src={promptImagePreviewUrl} alt="アップロード画像のプレビュー" />
                      <div className="prompt-image-preview__meta">
                        <span id="promptImagePreviewName">{promptImagePreviewName}</span>
                        <button
                          type="button"
                          id="promptImageClearButton"
                          className="prompt-image-clear-btn"
                          onClick={() => {
                            clearPromptImageSelection();
                          }}
                        >
                          <i className="bi bi-x-lg"></i>
                          <span>画像を外す</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="form-group form-group--toggle">
                  <label className="composer-toggle" htmlFor="guardrail-checkbox">
                    <input
                      type="checkbox"
                      id="guardrail-checkbox"
                      checked={guardrailEnabled}
                      onChange={(event) => {
                        setGuardrailEnabled(event.target.checked);
                      }}
                    />
                    <span className="composer-toggle__copy">
                      <strong>入出力例を追加する</strong>
                      <small>
                        保存・再利用しやすい投稿にするため、プロンプトの使い方を例で添えます。
                      </small>
                    </span>
                  </label>
                </div>

                <div id="guardrail-fields" style={{ display: guardrailEnabled ? "block" : "none" }}>
                  <div className="form-group">
                    <label htmlFor="prompt-input-example">入力例（プロンプト内容とは別にしてください）</label>
                    <textarea
                      id="prompt-input-example"
                      rows={3}
                      placeholder="例: 夏休みの思い出をテーマにした短いエッセイを書いてください。"
                      ref={promptPostInputExamplesRef}
                      value={postInputExample}
                      onChange={(event) => {
                        setPostInputExample(event.target.value);
                        updatePromptFeedbackErrorIfNeeded();
                      }}
                    ></textarea>
                  </div>
                  <div className="form-group">
                    <label htmlFor="prompt-output-example">出力例</label>
                    <textarea
                      id="prompt-output-example"
                      rows={3}
                      placeholder="例: 夏休みのある日、私は家族と一緒に海辺へ出かけました。波の音と潮風に包まれながら、子供の頃の記憶がよみがえり、心が温かくなりました。その日は一生忘れられない、宝物のような時間となりました。"
                      ref={promptPostOutputExamplesRef}
                      value={postOutputExample}
                      onChange={(event) => {
                        setPostOutputExample(event.target.value);
                        updatePromptFeedbackErrorIfNeeded();
                      }}
                    ></textarea>
                  </div>
                </div>

                <button type="submit" className="submit-btn" disabled={isPostSubmitting}>
                  <i className={`bi ${isPostSubmitting ? "bi-stars" : "bi-upload"}`}></i>
                  {isPostSubmitting ? " 投稿を準備中..." : " 投稿する"}
                </button>
              </form>
            </div>
          </div>
        </div>

        <div
          id="promptDetailModal"
          className={`post-modal${activeModal === "detail" ? " show" : ""}`}
          role="dialog"
          aria-modal="true"
          aria-labelledby="modalPromptTitle"
          aria-hidden={activeModal === "detail" ? "false" : "true"}
          ref={promptDetailModalRef}
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              closeModal("detail");
            }
          }}
        >
          <div className="post-modal-content" tabIndex={-1}>
            <button
              type="button"
              className="close-btn"
              id="closePromptDetailModal"
              aria-label="詳細モーダルを閉じる"
              ref={promptDetailCloseButtonRef}
              onClick={() => {
                closeModal("detail");
              }}
            >
              &times;
            </button>
            <h2 id="modalPromptTitle">{detailPrompt?.title || "プロンプト詳細"}</h2>

            <div className="modal-content-body">
              <div className="form-group">
                <label>
                  <strong>タイプ:</strong>
                </label>
                <p id="modalPromptType">
                  {detailPrompt ? getPromptTypeLabel(normalizePromptType(detailPrompt.prompt_type)) : ""}
                </p>
              </div>

              {detailPrompt?.reference_image_url ? (
                <div id="modalReferenceImageGroup" className="form-group" style={{ display: "block" }}>
                  <label>
                    <strong>作例画像:</strong>
                  </label>
                  <div className="modal-reference-image">
                    <img
                      id="modalReferenceImage"
                      src={detailPrompt.reference_image_url}
                      alt={`${detailPrompt.title} の作例画像`}
                    />
                  </div>
                </div>
              ) : null}

              <div className="form-group">
                <label>
                  <strong>カテゴリ:</strong>
                </label>
                <p id="modalPromptCategory">{detailPrompt?.category || ""}</p>
              </div>

              <div className="form-group">
                <label>
                  <strong>内容:</strong>
                </label>
                <p id="modalPromptContent">{detailPrompt?.content || ""}</p>
              </div>

              <div className="form-group">
                <label>
                  <strong>投稿者:</strong>
                </label>
                <p id="modalPromptAuthor">{detailPrompt?.author || ""}</p>
              </div>

              {detailPrompt?.ai_model ? (
                <div id="modalAiModelGroup" className="form-group" style={{ display: "block" }}>
                  <label>
                    <strong>使用AIモデル:</strong>
                  </label>
                  <p id="modalAiModel">{detailPrompt.ai_model}</p>
                </div>
              ) : null}

              {detailPrompt?.input_examples ? (
                <div id="modalInputExamplesGroup" className="form-group" style={{ display: "block" }}>
                  <label>
                    <strong>入力例:</strong>
                  </label>
                  <p id="modalInputExamples">{detailPrompt.input_examples}</p>
                </div>
              ) : null}

              {detailPrompt?.output_examples ? (
                <div id="modalOutputExamplesGroup" className="form-group" style={{ display: "block" }}>
                  <label>
                    <strong>出力例:</strong>
                  </label>
                  <p id="modalOutputExamples">{detailPrompt.output_examples}</p>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div
          id="promptShareModal"
          className={`post-modal prompt-share-modal${activeModal === "share" ? " show" : ""}`}
          role="dialog"
          aria-modal="true"
          aria-labelledby="promptShareModalTitle"
          aria-hidden={activeModal === "share" ? "false" : "true"}
          ref={promptShareModalRef}
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              closeModal("share");
            }
          }}
        >
          <div className="post-modal-content prompt-share-dialog" tabIndex={-1}>
            <button
              type="button"
              className="close-btn"
              id="closePromptShareModal"
              aria-label="共有モーダルを閉じる"
              onClick={() => {
                closeModal("share");
              }}
            >
              &times;
            </button>

            <h2 id="promptShareModalTitle">プロンプトを共有</h2>
            <p className="prompt-share-dialog__lead">
              このプロンプト専用のURLをコピーしたり、そのまま共有できます。
            </p>

            <div className="prompt-share-dialog__row">
              <input
                type="text"
                id="prompt-share-link-input"
                readOnly
                placeholder="共有リンクを準備しています"
                value={shareUrl}
              />
            </div>

            <p
              id="prompt-share-status"
              className={`prompt-share-dialog__status${shareStatus.isError ? " prompt-share-dialog__status--error" : ""}`}
            >
              {shareStatus.text}
            </p>

            <div className="prompt-share-dialog__actions">
              <button
                type="button"
                id="prompt-share-copy-btn"
                className="submit-btn prompt-share-icon-btn"
                aria-label="リンクをコピー"
                title="リンクをコピー"
                ref={promptShareCopyButtonRef}
                disabled={shareActionLoading}
                onClick={async () => {
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
                }}
              >
                <i className="bi bi-files" aria-hidden="true"></i>
              </button>

              {supportsNativeShare ? (
                <button
                  type="button"
                  id="prompt-share-web-btn"
                  className="submit-btn prompt-share-icon-btn"
                  aria-label="端末で共有"
                  title="端末で共有"
                  disabled={shareActionLoading}
                  onClick={async () => {
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
                  }}
                >
                  <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
                </button>
              ) : null}
            </div>

            <div className="prompt-share-dialog__sns">
              <a id="prompt-share-sns-x" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.x}>
                <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
                  ></path>
                </svg>
                <span>X</span>
              </a>
              <a id="prompt-share-sns-line" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.line}>
                <i className="bi bi-chat-dots"></i>
                <span>LINE</span>
              </a>
              <a
                id="prompt-share-sns-facebook"
                target="_blank"
                rel="noopener noreferrer"
                href={shareSnsLinks.facebook}
              >
                <i className="bi bi-facebook"></i>
                <span>Facebook</span>
              </a>
            </div>
          </div>
        </div>

        <button
          id="openPostModal"
          className="new-prompt-btn"
          aria-label="新しいプロンプトを投稿"
          data-tooltip="新しいプロンプトを投稿"
          data-tooltip-placement="left"
          type="button"
          onClick={openComposerModal}
        >
          <i className="bi bi-plus-lg" ref={promptNewButtonIconRef}></i>
        </button>
      </div>
    </>
  );
}
