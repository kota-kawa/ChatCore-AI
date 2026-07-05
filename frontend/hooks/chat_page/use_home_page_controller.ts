import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import useSWR from "swr";
import { useBodyScrollLock } from "../use_body_scroll_lock";
import { useHomePageChatState } from "./use_home_page_chat_state";
import { useHomePageNewPromptState } from "./use_home_page_new_prompt_state";
import { useHomePageShareState } from "./use_home_page_share_state";
import { useHomePageShareActions } from "./use_home_page_share_actions";
import { useHomePageTaskState } from "./use_home_page_task_state";
import { useHomePageTaskActions } from "./use_home_page_task_actions";
import { useHomePageUiState } from "./use_home_page_ui_state";
import { useHomePageAiAgentState } from "./use_home_page_ai_agent_state";
import { useHomePageGenerationActions } from "./use_home_page_generation_actions";
import { useHomePageRoomActions } from "./use_home_page_room_actions";
import { useHomePageProjects } from "./use_home_page_projects";
import { setLoggedInState } from "../../scripts/core/app_state";
import { CurrentUserAuthError, readCurrentUserLoggedIn } from "../../lib/chat_page/auth_status";
import { CHAT_ROOMS_PAGE_SIZE } from "../../lib/chat_page/constants";
import {
  normalizeChatRoomsPayload,
} from "../../lib/chat_page/api_contract";
import {
  mergeUniqueChatRooms,
} from "../../lib/chat_page/home_page_controller_utils";
import {
  consumeAuthSuccessHint,
  isCachedAuthStateFresh,
  readActiveStoredGenerationState,
  readStoredActiveChatRoom,
  readStoredHomePageViewState,
  readCachedAuthState,
  writeCachedAuthState,
} from "../../lib/chat_page/storage";
import {
  createGenerationGuard,
  type GenerationGuard,
} from "../../lib/chat_page/generation_guard";
import type {
  ChatRoomsPage,
  PromptAssistController,
} from "../../lib/chat_page/types";
import { showToast } from "../../scripts/core/toast";
import {
  extractApiErrorMessage,
  fetchJsonOrThrow,
  readJsonBodySafe,
} from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { copyTextToClipboard } from "../../scripts/chat/message_utils";
import { initPromptAssist } from "../../scripts/components/prompt_assist";
import {
  invalidateTasksCache,
} from "../../scripts/setup/setup_tasks_cache";
import { bindSetupViewportFit, scheduleSetupViewportFit } from "../../scripts/setup/setup_viewport";

const CHAT_SIDEBAR_OVERLAY_QUERY = "(max-width: 992px)";
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

// チャット画面復元のプリハイドレーションフラグ（_document.tsx のブートスクリプトが設定）。
// Pre-hydration flag for chat-view restores, set by the bootstrap script in _document.tsx.
const HOME_BOOT_VIEW_ATTRIBUTE = "data-cc-home-boot-view";
// 入場アニメーション（最長 0.73s = chat-area の delay 0.18s + duration 0.55s）の
// 元の再生時間を過ぎてからフラグを解除するための待機時間。
// Wait long enough to exceed the entrance animations' original play time
// (max 0.73s = chat-area delay 0.18s + duration 0.55s) before releasing the flag.
const HOME_BOOT_VIEW_RELEASE_DELAY_MS = 1000;

function isOverlaySidebarViewport() {
  return typeof window !== "undefined" && window.matchMedia(CHAT_SIDEBAR_OVERLAY_QUERY).matches;
}

const buildChatRoomsPageUrl = (cursor?: string | null): string => {
  const params = new URLSearchParams({
    limit: String(CHAT_ROOMS_PAGE_SIZE),
  });
  if (cursor) {
    params.set("cursor", cursor);
  }
  return `/api/get_chat_rooms?${params.toString()}`;
};

const fetchChatRoomsPage = async (url: string): Promise<ChatRoomsPage> => {
  const response = await resilientFetch(url, { credentials: "same-origin" });
  const rawPayload = await readJsonBodySafe(response);
  const payload = normalizeChatRoomsPayload(rawPayload);

  if (!response.ok || payload.error) {
    throw new Error(extractApiErrorMessage(rawPayload, "ルーム一覧取得に失敗しました。", response.status));
  }

  return payload;
};

export function useHomePageController() {
  const {
    loggedIn,
    setLoggedIn,
    authResolved,
    setAuthResolved,
    pageViewState,
    setPageViewState,
    isChatVisible,
    isSetupVisible,
    isChatLaunching,
    setupInfo,
    setSetupInfo,
    temporaryModeEnabled,
    setTemporaryModeEnabled,
    storedSetupStateLoaded,
    modelMenuOpen,
    setModelMenuOpen,
    chatHeaderModelMenuOpen,
    setChatHeaderModelMenuOpen,
    selectedModel,
    setSelectedModel,
    modelSelectRef,
    chatHeaderModelSelectRef,
    selectedModelLabel,
    selectedModelShortLabel,
  } = useHomePageUiState();

  const {
    tasks,
    setTasks,
    tasksExpanded,
    setTasksExpanded,
    taskCollapseLimit,
    isTaskOrderEditing,
    setIsTaskOrderEditing,
    taskDetail,
    setTaskDetail,
    launchingTaskName,
    setLaunchingTaskName,
    draggingTaskIndex,
    setDraggingTaskIndex,
    taskLaunchInProgressRef,
    taskEditModalOpen,
    setTaskEditModalOpen,
    taskEditForm,
    setTaskEditForm,
    showTaskToggleButton,
    visibleTaskCountText,
  } = useHomePageTaskState();

  const {
    isNewPromptModalOpen,
    setIsNewPromptModalOpen,
    guardrailEnabled,
    setGuardrailEnabled,
    newPromptTitle,
    setNewPromptTitle,
    newPromptContent,
    setNewPromptContent,
    newPromptInputExample,
    setNewPromptInputExample,
    newPromptOutputExample,
    setNewPromptOutputExample,
    newPromptStatus,
    setNewPromptStatus,
    isPromptSubmitting,
    setIsPromptSubmitting,
    newPromptAssistRootRef,
    titleInputRef,
    contentInputRef,
    inputExampleRef,
    outputExampleRef,
    promptAssistControllerRef,
  } = useHomePageNewPromptState();

  const {
    chatRooms,
    setChatRooms,
    chatRoomsHasMore,
    setChatRoomsHasMore,
    chatRoomsNextCursor,
    setChatRoomsNextCursor,
    isLoadingMoreChatRooms,
    setIsLoadingMoreChatRooms,
    currentRoomId,
    setCurrentRoomId,
    currentRoomMode,
    setCurrentRoomMode,
    messages,
    setMessages,
    chatInput,
    setChatInput,
    attachedFiles,
    setAttachedFiles,
    isGenerating,
    setIsGenerating,
    historyHasMore,
    setHistoryHasMore,
    historyNextBeforeId,
    setHistoryNextBeforeId,
    isLoadingOlder,
    setIsLoadingOlder,
    sidebarOpen,
    setSidebarOpen,
    openRoomActionsFor,
    setOpenRoomActionsFor,
    isRoomSelectionMode,
    setIsRoomSelectionMode,
    selectedRoomIds,
    setSelectedRoomIds,
    isBulkDeletingRooms,
    setIsBulkDeletingRooms,
    chatMessageListResetKey,
    setChatMessageListResetKey,
    chatMessagesRef,
    currentRoomIdRef,
    streamLastEventIdByRoomRef,
    abortControllerRef,
    messageSeqRef,
    pendingAutoScrollRef,
    prependScrollRestoreRef,
  } = useHomePageChatState();

  const {
    shareModalOpen,
    setShareModalOpen,
    shareStatus,
    setShareStatus,
    shareUrl,
    setShareUrl,
    shareLoading,
    setShareLoading,
    shareCacheRef,
    shareXUrl,
    shareLineUrl,
    shareFacebookUrl,
    supportsNativeShare,
  } = useHomePageShareState();

  const {
    isAiAgentModalOpen,
    openAiAgentModal,
    closeAiAgentModal,
    toggleAiAgentModal,
  } = useHomePageAiAgentState();

  const {
    closeShareModal,
    createShareLink,
    openShareModal,
    copyShareLink,
    shareWithNativeSheet,
  } = useHomePageShareActions({
    currentRoomIdRef,
    currentRoomMode,
    shareUrl,
    setShareStatus,
    setShareUrl,
    setShareLoading,
    setShareModalOpen,
    shareCacheRef,
  });

  const draggingTaskIndexRef = useRef<number | null>(null);
  const trackedTimeoutIdsRef = useRef<Set<number>>(new Set());
  const localStorageWarningShownRef = useRef(false);
  const loadingMoreChatRoomsRef = useRef(false);
  // Tracks whether the user has scrolled past the first sidebar page. Once true,
  // background revalidation of the first page must not rewind the pagination
  // cursor (see the cachedChatRoomsPage effect below).
  const hasLoadedMoreChatRoomsRef = useRef(false);
  const generationGuardRef = useRef<GenerationGuard | null>(null);
  if (!generationGuardRef.current) {
    generationGuardRef.current = createGenerationGuard();
  }
  const {
    refreshTasks,
    toggleTaskOrderEditing,
    handleTaskDragStart,
    handleTaskDragEnd,
    handleTaskDelete,
    openTaskEditModal,
    closeTaskEditModal,
    handleTaskEditSave,
  } = useHomePageTaskActions({
    tasks,
    setTasks,
    isTaskOrderEditing,
    setIsTaskOrderEditing,
    setTasksExpanded,
    setDraggingTaskIndex,
    draggingTaskIndexRef,
    taskEditForm,
    setTaskEditForm,
    setTaskEditModalOpen,
  });
  const {
    disconnectActiveGeneration,
    persistCurrentRoomId,
    loadLocalChatHistory,
    loadChatHistory,
    loadOlderChatHistory,
    createNewChatRoom,
    generateResponse,
    editAndRegenerateMessage,
    regenerateLastResponse,
    switchBranch,
    stopGeneration,
    removeStoredHistory,
  } = useHomePageGenerationActions({
    abortControllerRef,
    chatMessagesRef,
    currentRoomIdRef,
    currentRoomMode,
    generationGuardRef,
    historyHasMore,
    historyNextBeforeId,
    isLoadingOlder,
    localStorageWarningShownRef,
    messageSeqRef,
    pendingAutoScrollRef,
    prependScrollRestoreRef,
    streamLastEventIdByRoomRef,
    setChatRooms,
    setCurrentRoomId,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsGenerating,
    setIsLoadingOlder,
    setMessages,
  });
  const hasCurrentRoom = Boolean(currentRoomId);
  const {
    data: cachedChatRoomsPage,
    isLoading: isLoadingChatRoomsPage,
    mutate: mutateChatRooms,
  } = useSWR<ChatRoomsPage>(
    loggedIn ? buildChatRoomsPageUrl() : null,
    fetchChatRoomsPage,
    {
      revalidateOnFocus: true,
      dedupingInterval: 5000,
      keepPreviousData: true,
    },
  );
  const cachedChatRooms = cachedChatRoomsPage?.rooms;
  const isChatRoomsInitialLoading = loggedIn && isLoadingChatRoomsPage && chatRooms.length === 0;

  const loadMoreChatRooms = useCallback(async () => {
    if (!loggedIn || !chatRoomsHasMore || isLoadingMoreChatRooms || loadingMoreChatRoomsRef.current) return;
    const cursor = chatRoomsNextCursor;
    if (!cursor) return;

    loadingMoreChatRoomsRef.current = true;
    setIsLoadingMoreChatRooms(true);
    try {
      const page = await fetchChatRoomsPage(buildChatRoomsPageUrl(cursor));
      hasLoadedMoreChatRoomsRef.current = true;
      setChatRooms((previous) => mergeUniqueChatRooms(previous, page.rooms));
      setChatRoomsHasMore(page.pagination.hasMore);
      setChatRoomsNextCursor(page.pagination.nextCursor);
    } catch (error) {
      console.error("ルーム一覧追加取得失敗:", error);
    } finally {
      loadingMoreChatRoomsRef.current = false;
      setIsLoadingMoreChatRooms(false);
    }
  }, [
    chatRoomsHasMore,
    chatRoomsNextCursor,
    isLoadingMoreChatRooms,
    loggedIn,
    setChatRooms,
    setChatRoomsHasMore,
    setChatRoomsNextCursor,
    setIsLoadingMoreChatRooms,
  ]);

  const closeOverlaySidebar = useCallback(() => {
    if (isOverlaySidebarViewport()) {
      setSidebarOpen(false);
    }
  }, [setSidebarOpen]);

  const resetChatRoomsPaginationWindow = useCallback(() => {
    loadingMoreChatRoomsRef.current = false;
    hasLoadedMoreChatRoomsRef.current = false;
    setIsLoadingMoreChatRooms(false);
  }, [setIsLoadingMoreChatRooms]);

  const prepareChatViewTransition = useCallback(() => {
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement) {
      activeElement.blur();
    }
  }, []);

  const clearTrackedTimeouts = useCallback(() => {
    trackedTimeoutIdsRef.current.forEach((timeoutId) => {
      window.clearTimeout(timeoutId);
    });
    trackedTimeoutIdsRef.current.clear();
  }, []);

  const scheduleTrackedTimeout = useCallback((callback: () => void, delayMs: number) => {
    const timeoutId = window.setTimeout(() => {
      trackedTimeoutIdsRef.current.delete(timeoutId);
      callback();
    }, delayMs);
    trackedTimeoutIdsRef.current.add(timeoutId);
    return timeoutId;
  }, []);

  // 次に作成するチャットを紐づけるプロジェクトID（「このプロジェクトで新規チャット」用）。
  // ref はルーム作成時に同期的に参照され、state はセットアップ画面のバッジ表示に使う。
  // Project id to attach to the next created chat ("new chat in this project").
  // The ref is read synchronously at room creation; the state drives the setup-view badge.
  const [pendingProjectId, setPendingProjectId] = useState<number | null>(null);
  const pendingProjectIdRef = useRef<number | null>(null);
  useEffect(() => {
    pendingProjectIdRef.current = pendingProjectId;
  }, [pendingProjectId]);
  const clearPendingProject = useCallback(() => {
    pendingProjectIdRef.current = null;
    setPendingProjectId(null);
  }, []);

  const projectActions = useHomePageProjects({
    loggedIn,
    pendingProjectIdRef,
    setPendingProjectId,
  });

  const {
    loadChatRooms,
    switchChatRoom,
    showSetupForm,
    handleAccessChat,
    handleNewChat,
    handleTaskCardLaunch,
    handleSetupSendMessage,
    handleSendMessage,
    handleRegenerateMessage,
    handleEditAndRegenerateMessage,
    handleSwitchBranch,
    handleChatInputKeyDown,
    handleDeleteRoom,
    handleBulkDeleteRooms,
    handleRenameRoom,
    enterRoomSelectionMode,
    toggleRoomSelection,
    cancelRoomSelection,
  } = useHomePageRoomActions({
    attachedFiles,
    setAttachedFiles,
    cachedChatRooms,
    chatInput,
    chatRooms,
    closeOverlaySidebar,
    closeShareModal,
    createNewChatRoom,
    currentRoomIdRef,
    editAndRegenerateMessage,
    fetchChatRoomsPage,
    generateResponse,
    regenerateLastResponse,
    switchBranch,
    isGenerating,
    isTaskOrderEditing,
    loadChatHistory,
    loadLocalChatHistory,
    loggedIn,
    mutateChatRooms,
    pageViewState,
    persistCurrentRoomId,
    prepareChatViewTransition,
    removeStoredHistory,
    selectedModel,
    setupInfo,
    stopGeneration,
    taskLaunchInProgressRef,
    temporaryModeEnabled,
    selectedRoomIds,
    setChatInput,
    setChatRooms,
    setChatRoomsHasMore,
    setChatRoomsNextCursor,
    setCurrentRoomMode,
    setHistoryHasMore,
    setIsBulkDeletingRooms,
    setChatMessageListResetKey,
    setHistoryNextBeforeId,
    setIsLoadingOlder,
    setIsRoomSelectionMode,
    setLaunchingTaskName,
    setMessages,
    setOpenRoomActionsFor,
    setPageViewState,
    setSelectedRoomIds,
    setSetupInfo,
    setShareStatus,
    setShareUrl,
    resetChatRoomsPaginationWindow,
    pendingProjectIdRef,
    clearPendingProject,
  });

  const resetNewPromptComposer = useCallback(() => {
    setIsPromptSubmitting(false);
    setNewPromptStatus({ message: "", variant: "info" });
    promptAssistControllerRef.current?.reset();
  }, []);

  const closeNewPromptModal = useCallback(() => {
    setIsNewPromptModalOpen(false);
    resetNewPromptComposer();
  }, [resetNewPromptComposer]);

  const openNewPromptModal = useCallback(() => {
    setIsNewPromptModalOpen(true);
    setNewPromptStatus({
      message: "タイトルか本文がある状態で AI 補助を使うと、提案の精度が上がります。",
      variant: "info",
    });
  }, []);

  const handlePromptSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (isPromptSubmitting) return;

      setIsPromptSubmitting(true);
      setNewPromptStatus({ message: "タスクを追加しています...", variant: "info" });

      try {
        const payload = {
          title: newPromptTitle,
          prompt_content: newPromptContent,
          input_examples: guardrailEnabled ? newPromptInputExample : "",
          output_examples: guardrailEnabled ? newPromptOutputExample : "",
        };

        const { payload: responsePayload } = await fetchJsonOrThrow<{ message?: string }>(
          "/api/add_task",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(payload),
          },
          {
            defaultMessage: "タスクの追加に失敗しました。",
            fetchImpl: resilientFetch,
          },
        );

        setNewPromptStatus({
          message:
            typeof responsePayload.message === "string" ? responsePayload.message : "タスクが追加されました。",
          variant: "success",
        });

        setNewPromptTitle("");
        setNewPromptContent("");
        setNewPromptInputExample("");
        setNewPromptOutputExample("");
        setGuardrailEnabled(false);

        invalidateTasksCache();
        await refreshTasks(true);

        scheduleTrackedTimeout(() => {
          closeNewPromptModal();
        }, 550);
      } catch (error) {
        setNewPromptStatus({
          message: error instanceof Error ? error.message : "エラーが発生しました。",
          variant: "error",
        });
        setIsPromptSubmitting(false);
      }
    },
    [
      closeNewPromptModal,
      guardrailEnabled,
      isPromptSubmitting,
      newPromptContent,
      newPromptInputExample,
      newPromptOutputExample,
      newPromptTitle,
      refreshTasks,
      scheduleTrackedTimeout,
    ],
  );

  useEffect(() => {
    void import("../../scripts/core/csrf").then(({ primeCsrfToken }) => {
      void primeCsrfToken();
    });
    void import("../../scripts/components/popup_menu");
    void import("../../scripts/components/chat/popup_menu");
    void import("../../scripts/components/user_icon");
  }, []);

  useIsomorphicLayoutEffect(() => {
    document.body.classList.add("chat-page");
    return () => {
      clearTrackedTimeouts();
      disconnectActiveGeneration();
      document.body.classList.remove("chat-page");
      document.body.classList.remove("chat-view-active");
      document.body.classList.remove("setup-view-active");
      document.body.classList.remove("sidebar-visible");
      document.body.classList.remove("new-prompt-modal-open");
    };
  }, [clearTrackedTimeouts, disconnectActiveGeneration]);

  useEffect(() => {
    const mediaQuery = window.matchMedia(CHAT_SIDEBAR_OVERLAY_QUERY);
    const syncSidebarWithViewport = () => {
      setSidebarOpen(!mediaQuery.matches);
    };

    syncSidebarWithViewport();
    mediaQuery.addEventListener("change", syncSidebarWithViewport);

    return () => {
      mediaQuery.removeEventListener("change", syncSidebarWithViewport);
    };
  }, [setSidebarOpen]);

  useIsomorphicLayoutEffect(() => {
    const chatViewActive = pageViewState === "chat" || pageViewState === "launching";
    document.body.classList.toggle("setup-view-active", pageViewState === "setup");

    if (chatViewActive) {
      document.body.classList.add("chat-view-active");
      return;
    }

    if (!document.body.classList.contains("chat-view-active")) {
      return;
    }

    // chat-view-active 切替は .chat-page-shell の positioning context を fixed ⇄ flow に
    // 切り替えるため、即時に外すと #chat-container の退場トランジション中にレイアウトが
    // ジャンプしてガタつく。退場アニメーション完了後にクラスを外して安定させる。
    const timeoutId = window.setTimeout(() => {
      document.body.classList.remove("chat-view-active");
    }, 480);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [pageViewState]);

  useEffect(() => {
    const root = document.documentElement;
    let rafId: number | null = null;
    let settleTimeout: number | null = null;

    const writeViewportVars = () => {
      rafId = null;
      const visualViewport = window.visualViewport;
      const height = visualViewport?.height ?? window.innerHeight;
      const offsetTop = visualViewport?.offsetTop ?? 0;
      const layoutHeight = window.innerHeight || height;
      const keyboardInset = Math.max(0, Math.round(layoutHeight - height - offsetTop));

      root.style.setProperty("--chat-visual-viewport-height", `${Math.max(0, Math.round(height))}px`);
      root.style.setProperty("--chat-visual-viewport-offset-top", `${Math.max(0, Math.round(offsetTop))}px`);
      root.style.setProperty("--chat-keyboard-inset", `${keyboardInset}px`);
      root.dataset.chatKeyboardOpen = keyboardInset > 24 ? "true" : "false";
    };

    const updateViewportVars = () => {
      if (rafId !== null) return;
      rafId = window.requestAnimationFrame(writeViewportVars);
    };

    // iOS は keyboard を閉じた後に visualViewport.resize がしばらく遅延する
    // ことがあるため、フォーカスが外れたら少し遅らせて強制再計測する
    const scheduleSettleTick = () => {
      if (settleTimeout !== null) {
        window.clearTimeout(settleTimeout);
      }
      settleTimeout = window.setTimeout(() => {
        settleTimeout = null;
        writeViewportVars();
      }, 250);
    };

    writeViewportVars();
    window.addEventListener("resize", updateViewportVars);
    window.addEventListener("orientationchange", updateViewportVars);
    window.visualViewport?.addEventListener("resize", updateViewportVars);
    window.visualViewport?.addEventListener("scroll", updateViewportVars);
    document.addEventListener("focusin", updateViewportVars);
    document.addEventListener("focusout", scheduleSettleTick);

    return () => {
      if (rafId !== null) window.cancelAnimationFrame(rafId);
      if (settleTimeout !== null) window.clearTimeout(settleTimeout);
      window.removeEventListener("resize", updateViewportVars);
      window.removeEventListener("orientationchange", updateViewportVars);
      window.visualViewport?.removeEventListener("resize", updateViewportVars);
      window.visualViewport?.removeEventListener("scroll", updateViewportVars);
      document.removeEventListener("focusin", updateViewportVars);
      document.removeEventListener("focusout", scheduleSettleTick);
      root.style.removeProperty("--chat-visual-viewport-height");
      root.style.removeProperty("--chat-visual-viewport-offset-top");
      root.style.removeProperty("--chat-keyboard-inset");
      delete root.dataset.chatKeyboardOpen;
    };
  }, []);

  useEffect(() => {
    if (pageViewState !== "chat" || !sidebarOpen || !isOverlaySidebarViewport()) {
      document.body.classList.remove("sidebar-visible");
      return;
    }
    document.body.classList.add("sidebar-visible");
  }, [pageViewState, sidebarOpen]);

  useEffect(() => {
    document.body.classList.toggle("new-prompt-modal-open", isNewPromptModalOpen);
  }, [isNewPromptModalOpen]);

  const hasBlockingModalOpen =
    isNewPromptModalOpen || shareModalOpen || taskEditModalOpen || Boolean(taskDetail);

  useBodyScrollLock(hasBlockingModalOpen);

  useEffect(() => {
    bindSetupViewportFit();
    scheduleSetupViewportFit();
  }, []);

  useEffect(() => {
    if (pageViewState === "setup") {
      scheduleSetupViewportFit();
    }
  }, [authResolved, loggedIn, pageViewState, tasks.length, tasksExpanded]);

  useEffect(() => {
    currentRoomIdRef.current = currentRoomId;
  }, [currentRoomId]);

  useEffect(() => {
    const container = chatMessagesRef.current;
    if (!container) return;

    const restore = prependScrollRestoreRef.current;
    if (restore) {
      const delta = container.scrollHeight - restore.prevScrollHeight;
      container.scrollTop = restore.prevScrollTop + delta;
      prependScrollRestoreRef.current = null;
      pendingAutoScrollRef.current = false;
      return;
    }

    if (!pendingAutoScrollRef.current) return;
    pendingAutoScrollRef.current = false;
    container.scrollTop = container.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const applyCachedAuth = consumeAuthSuccessHint();
    const cachedAuthState = readCachedAuthState();
    const canFallback = isCachedAuthStateFresh() && cachedAuthState !== null;

    if (cachedAuthState !== null) {
      setLoggedIn(cachedAuthState);
    }

    if (applyCachedAuth && cachedAuthState === null) {
      setLoggedIn(true);
    }

    let cancelled = false;

    resilientFetch("/api/current_user", { credentials: "same-origin" })
      .then(readCurrentUserLoggedIn)
      .then((nextLoggedIn) => {
        if (cancelled) return;
        writeCachedAuthState(nextLoggedIn);
        setLoggedIn(nextLoggedIn);
      })
      .catch((error) => {
        if (cancelled) return;
        if (error instanceof CurrentUserAuthError) {
          writeCachedAuthState(false);
          setLoggedIn(false);
          showToast(
            error.status === 401
              ? "ログインセッションが切れました。再ログインしてください。"
              : "認証状態を確認できませんでした。再ログインしてください。",
            { variant: "error" },
          );
          return;
        }
        if (!canFallback) {
          setLoggedIn(false);
        }
      })
      .finally(() => {
        if (cancelled) return;
        setAuthResolved(true);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setLoggedInState(loggedIn);
  }, [loggedIn]);

  useEffect(() => {
    if (!cachedChatRoomsPage) return;
    const nextRooms = cachedChatRoomsPage.rooms;
    const hasPaginated = hasLoadedMoreChatRoomsRef.current;
    setChatRooms((previous) =>
      hasPaginated ? mergeUniqueChatRooms(nextRooms, previous) : nextRooms,
    );
    // A background revalidation of the first page (focus, room mutations, etc.)
    // must not rewind the cursor once the user has scrolled to additional pages,
    // otherwise the next scroll re-fetches already-visible rooms and the list
    // appears stuck. Only adopt the first page's cursor while still on page one.
    if (!hasPaginated) {
      setChatRoomsHasMore(cachedChatRoomsPage.pagination.hasMore);
      setChatRoomsNextCursor(cachedChatRoomsPage.pagination.nextCursor);
    }

    const activeRoomId = currentRoomIdRef.current;
    if (!activeRoomId) return;

    const activeRoom = nextRooms.find((room) => room.id === activeRoomId);
    if (activeRoom) {
      setCurrentRoomMode(activeRoom.mode);
    }
  }, [cachedChatRoomsPage, setChatRooms, setChatRoomsHasMore, setChatRoomsNextCursor, setCurrentRoomMode]);

  useEffect(() => {
    if (!authResolved) return;
    if (!loggedIn && isTaskOrderEditing) {
      setIsTaskOrderEditing(false);
    }
  }, [authResolved, isTaskOrderEditing, loggedIn]);

  useEffect(() => {
    if (!authResolved) return;
    void refreshTasks(true);
    if (!loggedIn) {
      setChatRooms([]);
      setChatRoomsHasMore(false);
      setChatRoomsNextCursor(null);
      loadingMoreChatRoomsRef.current = false;
      hasLoadedMoreChatRoomsRef.current = false;
      setIsLoadingMoreChatRooms(false);
      setCurrentRoomMode("normal");
    }
  }, [authResolved, loggedIn, refreshTasks, setChatRoomsHasMore, setChatRoomsNextCursor, setIsLoadingMoreChatRooms]);

  useEffect(() => {
    if (tasks.length <= taskCollapseLimit) {
      setTasksExpanded(false);
    }
  }, [taskCollapseLimit, tasks.length]);

  // 前回のビュー（チャット画面など）とアクティブルームの復元。最初のペイント前に
  // 反映しないとセットアップ画面が一瞬表示されてからチャット画面へ切り替わるため、
  // layout effect で同期的に復元する（ローカル履歴の読み込みも同じパスで行われ、
  // 初回描画にメッセージが含まれる）。
  // Restore the previous view (e.g. chat) and active room. This must run before
  // the first paint — otherwise the setup view flashes briefly and then swaps to
  // the chat view — so restore synchronously in a layout effect (local history
  // loads on the same path, so the first paint already contains the messages).
  useIsomorphicLayoutEffect(() => {
    try {
      const storedViewState = readStoredHomePageViewState();
      const activeGeneration = readActiveStoredGenerationState();
      if (activeGeneration) {
        setCurrentRoomId(activeGeneration.roomId);
        currentRoomIdRef.current = activeGeneration.roomId;
        setCurrentRoomMode(activeGeneration.roomMode);
        setPageViewState("chat");
        // 復元時はローカル履歴を末尾アンカリングしたいので、一覧を新規マウントさせる。
        // key は currentRoomId に依存しなくなったため、ここで明示的に reset する。
        setChatMessageListResetKey((previous) => previous + 1);
        loadLocalChatHistory(activeGeneration.roomId);
        void loadChatHistory(activeGeneration.roomId, true);
        return;
      }

      const storedActiveRoom = readStoredActiveChatRoom();
      if (storedActiveRoom) {
        setCurrentRoomId(storedActiveRoom.roomId);
        currentRoomIdRef.current = storedActiveRoom.roomId;
        setCurrentRoomMode(storedActiveRoom.roomMode);

        if (storedViewState === "chat") {
          setPageViewState("chat");
          setChatMessageListResetKey((previous) => previous + 1);
          loadLocalChatHistory(storedActiveRoom.roomId);
          void loadChatHistory(storedActiveRoom.roomId, true);
        }
        return;
      }

      if (storedViewState === "chat") {
        setPageViewState("chat");
        setCurrentRoomMode("normal");
        setChatMessageListResetKey((previous) => previous + 1);
        setMessages([]);
        setHistoryHasMore(false);
        setHistoryNextBeforeId(null);
        setIsLoadingOlder(false);
      }
    } catch {
      // ignore localStorage failures
    }
  }, [
    loadChatHistory,
    loadLocalChatHistory,
    setChatMessageListResetKey,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsLoadingOlder,
    setMessages,
    setPageViewState,
  ]);

  // _document.tsx のブートスクリプトが立てるプリハイドレーション用フラグを解除する。
  // フラグが立っている間は CSS がセットアップ画面を隠し、ビュー切替のトランジション・
  // 入場アニメーションを即完了扱いにするため、復元されたチャット画面はアニメーション
  // なしで即座に表示される。解除は入場アニメーションの元の再生時間（最長 0.73s）より
  // 後に行う必要がある。CSS は animation-name を保持したまま duration を短縮している
  // ため、それより早く解除すると再生途中と見なされて動き出してしまう。復元結果が
  // セットアップ画面だった場合（保存状態の不整合など）は、画面を隠したままにしない
  // よう即時解除する。
  // Release the pre-hydration flag set by the bootstrap script in _document.tsx.
  // While present, CSS hides the setup view and makes the view-switch transitions
  // and entrance animations finish instantly, so the restored chat view appears
  // without animating. The release must happen after the original play time of the
  // entrance animations (max 0.73s): the CSS keeps animation-name and only shortens
  // the duration, so releasing earlier would put them mid-flight and move things.
  // If restoration lands on the setup view (stale stored state, etc.), release
  // immediately so the setup view is not left hidden.
  useEffect(() => {
    const root = document.documentElement;
    if (!root.hasAttribute(HOME_BOOT_VIEW_ATTRIBUTE)) return;

    if (pageViewState === "setup") {
      root.removeAttribute(HOME_BOOT_VIEW_ATTRIBUTE);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      root.removeAttribute(HOME_BOOT_VIEW_ATTRIBUTE);
    }, HOME_BOOT_VIEW_RELEASE_DELAY_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [pageViewState]);

  useEffect(() => {
    const onOutsideClick = (event: MouseEvent) => {
      if (!(event.target instanceof Element)) return;
      const target = event.target;

      if (modelMenuOpen && modelSelectRef.current && !modelSelectRef.current.contains(target)) {
        setModelMenuOpen(false);
      }

      if (chatHeaderModelMenuOpen && chatHeaderModelSelectRef.current && !chatHeaderModelSelectRef.current.contains(target)) {
        setChatHeaderModelMenuOpen(false);
      }

      if (openRoomActionsFor && !target.closest(".room-actions-menu") && !target.closest(".room-actions-icon")) {
        setOpenRoomActionsFor(null);
      }

      if (
        sidebarOpen &&
        isOverlaySidebarViewport() &&
        !target.closest(".sidebar") &&
        !target.closest("#sidebar-toggle")
      ) {
        setSidebarOpen(false);
      }
    };

    document.addEventListener("click", onOutsideClick);
    return () => {
      document.removeEventListener("click", onOutsideClick);
    };
  }, [modelMenuOpen, chatHeaderModelMenuOpen, openRoomActionsFor, sidebarOpen]);

  useEffect(() => {
    let lastWidth = typeof window === "undefined" ? 0 : window.innerWidth;
    const onWindowResize = () => {
      const nextWidth = window.innerWidth;
      // Only treat width changes as a real resize; ignore height-only changes
      // caused by the on-screen keyboard opening/closing.
      if (Math.abs(nextWidth - lastWidth) >= 1) {
        lastWidth = nextWidth;
        closeOverlaySidebar();
        scheduleSetupViewportFit();
      }
    };
    const onVisualViewportResize = () => {
      // Re-run setup density on viewport changes, but never auto-close the
      // sidebar — that would flicker every time the soft keyboard appears.
      scheduleSetupViewportFit();
    };

    window.addEventListener("resize", onWindowResize);
    window.visualViewport?.addEventListener("resize", onVisualViewportResize);

    return () => {
      window.removeEventListener("resize", onWindowResize);
      window.visualViewport?.removeEventListener("resize", onVisualViewportResize);
    };
  }, [closeOverlaySidebar]);

  useEffect(() => {
    if (!isNewPromptModalOpen && !shareModalOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isNewPromptModalOpen) {
        if (isPromptSubmitting) return;
        closeNewPromptModal();
        return;
      }
      if (shareModalOpen) {
        closeShareModal();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeNewPromptModal, closeShareModal, isNewPromptModalOpen, isPromptSubmitting, shareModalOpen]);

  useEffect(() => {
    const onCodeCopyClick = (event: MouseEvent) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest<HTMLButtonElement>(".code-block-copy-btn");
      if (!button) return;

      const codeElement = button.closest(".code-block-container")?.querySelector("code");
      const code = codeElement?.textContent || "";
      const icon = button.querySelector("i");
      const textSpan = button.querySelector("span");
      const defaultLabel = textSpan?.dataset.defaultLabel || textSpan?.textContent || "Copy code";

      if (textSpan) {
        textSpan.dataset.defaultLabel = defaultLabel;
      }

      copyTextToClipboard(code)
        .then(() => {
          if (icon) {
            icon.classList.remove("bi-clipboard", "bi-x-lg");
            icon.classList.add("bi-check-lg");
            scheduleTrackedTimeout(() => {
              icon.classList.remove("bi-check-lg", "bi-x-lg");
              icon.classList.add("bi-clipboard");
            }, 2000);
          }
          if (textSpan) {
            textSpan.textContent = "Copied!";
            scheduleTrackedTimeout(() => {
              textSpan.textContent = defaultLabel;
            }, 2000);
          }
        })
        .catch(() => {
          if (icon) {
            icon.classList.remove("bi-clipboard", "bi-check-lg");
            icon.classList.add("bi-x-lg");
            scheduleTrackedTimeout(() => {
              icon.classList.remove("bi-check-lg", "bi-x-lg");
              icon.classList.add("bi-clipboard");
            }, 2000);
          }
          if (textSpan) {
            textSpan.textContent = "Failed";
            scheduleTrackedTimeout(() => {
              textSpan.textContent = defaultLabel;
            }, 2000);
          }
        });
    };

    document.addEventListener("click", onCodeCopyClick);
    return () => {
      document.removeEventListener("click", onCodeCopyClick);
    };
  }, [scheduleTrackedTimeout]);

  useEffect(() => {
    if (promptAssistControllerRef.current) return;
    if (!newPromptAssistRootRef.current) return;
    if (!titleInputRef.current || !contentInputRef.current || !inputExampleRef.current || !outputExampleRef.current) {
      return;
    }

    const controller = initPromptAssist({
      root: newPromptAssistRootRef.current,
      target: "task_modal",
      fields: {
        title: { label: "タイトル", element: titleInputRef.current, setValue: setNewPromptTitle },
        prompt_content: { label: "プロンプト内容", element: contentInputRef.current, setValue: setNewPromptContent },
        input_examples: { label: "入力例", element: inputExampleRef.current, setValue: setNewPromptInputExample },
        output_examples: { label: "出力例", element: outputExampleRef.current, setValue: setNewPromptOutputExample },
      },
      beforeApplyField: (fieldName) => {
        if (fieldName === "input_examples" || fieldName === "output_examples") {
          setGuardrailEnabled(true);
        }
      },
    });

    promptAssistControllerRef.current = (controller || null) as PromptAssistController | null;
  }, []);

  useEffect(() => {
    if (newPromptStatus.variant === "error") {
      setNewPromptStatus({ message: "", variant: "info" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newPromptTitle, newPromptContent, newPromptInputExample, newPromptOutputExample]);


  return {
    loggedIn,
    authResolved,
    // プロジェクト機能（一覧・詳細・CRUD・新規チャット紐づけ）
    // Projects feature (list, detail, CRUD, new-chat association)
    ...projectActions,
    pendingProjectId,
    clearPendingProject,
    pageViewState,
    isChatVisible,
    isSetupVisible,
    isChatLaunching,
    setupInfo,
    temporaryModeEnabled,
    storedSetupStateLoaded,
    selectedModel,
    modelMenuOpen,
    selectedModelLabel,
    tasks,
    isTaskOrderEditing,
    isNewPromptModalOpen,
    tasksExpanded,
    showTaskToggleButton,
    visibleTaskCountText,
    taskCollapseLimit,
    launchingTaskName,
    draggingTaskIndex,
    modelSelectRef,
    setSetupInfo,
    setTemporaryModeEnabled,
    setSelectedModel,
    setModelMenuOpen,
    toggleTaskOrderEditing,
    closeNewPromptModal,
    openNewPromptModal,
    handleTaskDragStart,
    handleTaskDragEnd,
    handleTaskCardLaunch,
    handleSetupSendMessage,
    handleTaskDelete,
    openTaskEditModal,
    setTaskDetail,
    setTasksExpanded,
    handleAccessChat,
    chatHeaderModelMenuOpen,
    selectedModelShortLabel,
    hasCurrentRoom,
    sidebarOpen,
    chatRooms,
    chatRoomsHasMore,
    isChatRoomsInitialLoading,
    isLoadingMoreChatRooms,
    currentRoomId,
    currentRoomMode,
    openRoomActionsFor,
    isRoomSelectionMode,
    selectedRoomIds,
    isBulkDeletingRooms,
    chatMessageListResetKey,
    historyHasMore,
    historyNextBeforeId,
    isLoadingOlder,
    messages,
    chatInput,
    attachedFiles,
    setAttachedFiles,
    isGenerating,
    chatHeaderModelSelectRef,
    chatMessagesRef,
    showSetupForm,
    setChatHeaderModelMenuOpen,
    openShareModal,
    handleNewChat,
    switchChatRoom,
    setOpenRoomActionsFor,
    handleRenameRoom,
    handleDeleteRoom,
    handleBulkDeleteRooms,
    enterRoomSelectionMode,
    toggleRoomSelection,
    cancelRoomSelection,
    setSidebarOpen,
    loadMoreChatRooms,
    loadOlderChatHistory,
    setChatInput,
    handleChatInputKeyDown,
    handleSendMessage,
    handleRegenerateMessage,
    handleEditAndRegenerateMessage,
    handleSwitchBranch,
    taskDetail,
    isPromptSubmitting,
    guardrailEnabled,
    newPromptTitle,
    newPromptContent,
    newPromptInputExample,
    newPromptOutputExample,
    newPromptStatus,
    titleInputRef,
    contentInputRef,
    inputExampleRef,
    outputExampleRef,
    newPromptAssistRootRef,
    handlePromptSubmit,
    setGuardrailEnabled,
    setNewPromptTitle,
    setNewPromptContent,
    setNewPromptInputExample,
    setNewPromptOutputExample,
    taskEditModalOpen,
    taskEditForm,
    closeTaskEditModal,
    setTaskEditForm,
    handleTaskEditSave,
    shareModalOpen,
    shareStatus,
    shareUrl,
    shareLoading,
    supportsNativeShare,
    shareXUrl,
    shareLineUrl,
    shareFacebookUrl,
    closeShareModal,
    copyShareLink,
    shareWithNativeSheet,
    isAiAgentModalOpen,
    openAiAgentModal,
    closeAiAgentModal,
    toggleAiAgentModal,
    };
    }
