// ホーム画面（pages/index.tsx）の状態と操作を束ねるコントローラー hook。UI・タスク・チャット・共有・プロジェクトなどの小さな hook を組み合わせ、認証確認・画面の復元・レイアウト同期の副作用を持つ。戻り値は HomePageContextProvider（contexts/chat_page/home_page_context.tsx）で配られる。
// Controller hook that ties together the home page (pages/index.tsx) state and actions. It composes the smaller UI / task / chat / share / project hooks and owns the side effects for auth checks, view restoration and layout sync. Its return value is distributed by HomePageContextProvider (contexts/chat_page/home_page_context.tsx).
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
import { releaseAuthBootAttribute } from "../../scripts/core/auth_state_cache";
import { CurrentUserAuthError, readCurrentUserLoggedIn } from "../../lib/chat_page/auth_status";
import { CHAT_ROOMS_PAGE_SIZE } from "../../lib/chat_page/constants";
import {
  normalizeChatRoomsPayload,
} from "../../lib/chat_page/api_contract";
import {
  mergeUniqueChatRooms,
} from "../../lib/chat_page/home_page_controller_utils";
import { moveFocusOutOfHiddenRegion } from "../../lib/chat_page/focus_management";
import { replaceToolApprovalInMessages } from "../../lib/chat_page/tool_approvals";
import type { ToolApprovalApi } from "../../types/generated/api_schemas";
import {
  consumeAuthSuccessHint,
  isCachedAuthStateFresh,
  readActiveStoredGenerationState,
  readStoredActiveChatRoom,
  readRestorableHomePageViewState,
  readCachedAuthState,
  reconcileStoredUserScope,
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
import { initPromptAssist } from "../../scripts/components/prompt_assist";
import {
  invalidateTasksCache,
} from "../../scripts/setup/setup_tasks_cache";
import { bindSetupViewportFit, scheduleSetupViewportFit } from "../../scripts/setup/setup_viewport";
import { useTranslation } from "../../contexts/locale_context";

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

// 幅が狭く、サイドバーが画面に重なって表示される（オーバーレイ）状態かどうか
// Whether the viewport is narrow enough that the sidebar is shown as an overlay
function isOverlaySidebarViewport() {
  return typeof window !== "undefined" && window.matchMedia(CHAT_SIDEBAR_OVERLAY_QUERY).matches;
}

// /api/current_user は認証済みのとき { user: { id, ... } } を返す。永続状態を
// ユーザーごとに区切るためだけに読み、失敗しても認証判定そのものには影響させない。
// /api/current_user returns { user: { id, ... } } once authenticated. This is read
// solely to scope persisted state per user; a parse failure never affects the
// auth decision itself.
async function readCurrentUserIdFromResponse(response: Response): Promise<string | null> {
  try {
    const data = (await response.json().catch(() => null)) as { user?: { id?: unknown } } | null;
    const id = data?.user?.id;
    if (typeof id === "number" && Number.isFinite(id)) return String(id);
    if (typeof id === "string" && id.trim()) return id.trim();
    return null;
  } catch {
    return null;
  }
}

// ルーム一覧 API の URL を作る。cursor があれば、その続きのページを指す
// Build the chat-rooms API URL; a cursor points at the following page
const buildChatRoomsPageUrl = (cursor?: string | null): string => {
  const params = new URLSearchParams({
    limit: String(CHAT_ROOMS_PAGE_SIZE),
  });
  if (cursor) {
    params.set("cursor", cursor);
  }
  return `/api/get_chat_rooms?${params.toString()}`;
};

// ルーム一覧の 1 ページを取得して正規化する。失敗時は例外にする（SWR のフェッチ関数としても使う）
// Fetch and normalize one page of chat rooms, throwing on failure (also used as the SWR fetcher)
const fetchChatRoomsPage = async (url: string): Promise<ChatRoomsPage> => {
  const response = await resilientFetch(url, { credentials: "same-origin" });
  const rawPayload = await readJsonBodySafe(response);
  const payload = normalizeChatRoomsPayload(rawPayload);

  if (!response.ok || payload.error) {
    throw new Error(extractApiErrorMessage(rawPayload, "ルーム一覧取得に失敗しました。", response.status));
  }

  return payload;
};

// ホーム画面の全状態を組み立てて返す。UI 状態、タスク、チャット、共有などの hook を呼び出し、それらをつなぐ処理と副作用をここに置く
// Assemble and return all home page state: calls the UI, task, chat and share hooks, and holds the glue logic and side effects between them
export function useHomePageController() {
  const { locale } = useTranslation();
  // localize は言語を ref から読む。コールバックを作り直さずに、最新の言語で文言を選べる
  // localize reads the language from a ref, so callbacks pick the latest language without being recreated
  const localeRef = useRef(locale);
  localeRef.current = locale;
  const localize = useCallback((ja: string, en: string) => localeRef.current === "en" ? en : ja, []);
  const {
    loggedIn,
    setLoggedIn,
    authResolved,
    setAuthResolved,
    authHintApplied,
    setAuthHintApplied,
    pageViewState,
    setPageViewState,
    isChatVisible,
    isSetupVisible,
    isChatLaunching,
    setupInfo,
    setSetupInfo,
    temporaryModeEnabled,
    setTemporaryModeEnabled,
    personalKnowledgeEnabled,
    setPersonalKnowledgeEnabled,
    sharedPromptsEnabled,
    setSharedPromptsEnabled,
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
    launchingTaskId,
    setLaunchingTaskId,
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

  // タスクのドラッグ中の位置を、イベント処理の途中でも同期的に読めるようにする ref
  // Ref to read the dragged task's index synchronously during event handling
  const draggingTaskIndexRef = useRef<number | null>(null);
  // scheduleTrackedTimeout で登録したタイマー ID。アンマウント時にまとめて解除する
  // Timer IDs registered via scheduleTrackedTimeout; cleared together on unmount
  const trackedTimeoutIdsRef = useRef<Set<number>>(new Set());
  // ルーム一覧の追加取得が実行中かどうか。state より先に同期的に判定でき、二重取得を防ぐ
  // Whether loading more rooms is in flight; unlike state it can be checked synchronously, preventing duplicate fetches
  const loadingMoreChatRoomsRef = useRef(false);
  // ユーザーがサイドバーの 1 ページ目より先まで読み込んだかを示す。true になったら、1 ページ目のバックグラウンド再検証でページングのカーソルを巻き戻してはいけない（下の cachedChatRoomsPage の effect を参照）。
  // Tracks whether the user has scrolled past the first sidebar page. Once true,
  // background revalidation of the first page must not rewind the pagination
  // cursor (see the cachedChatRoomsPage effect below).
  const hasLoadedMoreChatRoomsRef = useRef(false);
  // 回答生成を同時に 1 つに限るためのガード。一度だけ作成して保持する
  // Guard that limits answer generation to one at a time; created once and kept
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
    loggedIn,
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
    messageList: { messageSeqRef, setMessages },
    generationStream: {
      abortControllerRef,
      generationGuardRef,
      setIsGenerating,
      streamLastEventIdByRoomRef,
    },
    roomSelection: {
      currentRoomIdRef,
      currentRoomMode,
      setChatRooms,
      setCurrentRoomId,
      setCurrentRoomMode,
    },
    historyPagination: {
      historyHasMore,
      historyNextBeforeId,
      isLoadingOlder,
      setHistoryHasMore,
      setHistoryNextBeforeId,
      setIsLoadingOlder,
    },
    scrollRestore: { chatMessagesRef, pendingAutoScrollRef, prependScrollRestoreRef },
    retrievalSettings: { personalKnowledgeEnabled, sharedPromptsEnabled },
    setChatInput,
  });
  const hasCurrentRoom = Boolean(currentRoomId);
  // ログイン中だけルーム一覧の 1 ページ目を取得する。フォーカス復帰で再検証し、取得済みの値は再取得中も表示し続ける
  // Fetch the first page of rooms only while logged in; revalidate on focus and keep showing the previous data during revalidation
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

  // サイドバーのルーム一覧を次のページまで読み込み、既存の一覧に重複なく追加する
  // Load the next page of the sidebar room list and merge it in without duplicates
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

  // オーバーレイ表示のとき（幅が狭いとき）だけサイドバーを閉じる
  // Close the sidebar only in overlay mode (narrow viewports)
  const closeOverlaySidebar = useCallback(() => {
    if (isOverlaySidebarViewport()) {
      // サイドバーを支援技術から隠す前に、内部のフォーカスを開閉ボタンへ戻す。
      // Move focus before aria-hidden is applied to prevent hiding the focused room card.
      moveFocusOutOfHiddenRegion(
        document.getElementById("chat-room-sidebar"),
        document.getElementById("sidebar-toggle"),
      );
      setSidebarOpen(false);
    }
  }, [setSidebarOpen]);

  // 「すべて見る」などルーム一覧を目的にした遷移では、オーバーレイ幅でも一覧を最初に見せる。
  // 広い画面はビューポート同期でサイドバーが常に開いているので何もしない。
  // Transitions whose goal is the room list (e.g. "view all") show the list first even at
  // overlay widths. Wide viewports already keep the sidebar open, so nothing happens there.
  const openOverlaySidebar = useCallback(() => {
    if (isOverlaySidebarViewport()) {
      setSidebarOpen(true);
    }
  }, [setSidebarOpen]);

  // ルーム一覧のページングに関する追加取得の状態を初期化する
  // Reset the state tracking additional room-list pages
  const resetChatRoomsPaginationWindow = useCallback(() => {
    loadingMoreChatRoomsRef.current = false;
    hasLoadedMoreChatRoomsRef.current = false;
    setIsLoadingMoreChatRooms(false);
  }, [setIsLoadingMoreChatRooms]);

  // 画面の切り替え前に、フォーカス中の要素を外す
  // Blur the focused element before switching views
  const prepareChatViewTransition = useCallback(() => {
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement) {
      activeElement.blur();
    }
  }, []);

  // scheduleTrackedTimeout で登録した未実行のタイマーをすべて解除する
  // Cancel every timer still pending that was registered through scheduleTrackedTimeout
  const clearTrackedTimeouts = useCallback(() => {
    trackedTimeoutIdsRef.current.forEach((timeoutId) => {
      window.clearTimeout(timeoutId);
    });
    trackedTimeoutIdsRef.current.clear();
  }, []);

  // アンマウント時に解除できるよう、ID を記録しながらタイマーを張る
  // Set a timer while recording its ID so it can be cancelled on unmount
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

  // プロジェクト機能（一覧・詳細・作成など）。次の新規チャットに紐づけるプロジェクトを共有する
  // Project features (list, detail, create, ...), sharing the project to attach to the next new chat
  const projectActions = useHomePageProjects({
    loggedIn,
    pendingProjectIdRef,
    setPendingProjectId,
  });

  const {
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
    handleToggleRoomPin,
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
    openOverlaySidebar,
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
    hasMessages: messages.length > 0,
    persistCurrentRoomId,
    prepareChatViewTransition,
    removeStoredHistory,
    selectedModel,
    setupInfo,
    stopGeneration,
    taskLaunchInProgressRef,
    temporaryModeEnabled,
    setTemporaryModeEnabled,
    personalKnowledgeEnabled,
    setPersonalKnowledgeEnabled,
    sharedPromptsEnabled,
    setSharedPromptsEnabled,
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
    setLaunchingTaskId,
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

  // 承認 API が返した最新のカードで、表示中のメッセージの承認カードを差し替える。
  // Replace the displayed approval card with the latest one returned by the approval API.
  const applyToolApproval = useCallback((approval: ToolApprovalApi) => {
    setMessages((previous) => replaceToolApprovalInMessages(previous, approval));
  }, [setMessages]);

  // 新規タスクモーダルの送信中状態・メッセージ・AI 補助の状態を初期化する
  // Reset the new-task modal's submitting flag, status message and AI assistance state
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
      message: localize("タイトルか本文がある状態で AI 補助を使うと、提案の精度が上がります。", "Add a title or content before using AI assistance for better suggestions."),
      variant: "info",
    });
  }, []);

  // 新規タスクを /api/add_task へ送る。成功したら入力を空にしてタスク一覧を再取得し、少し待ってからモーダルを閉じる。入力例・出力例は guardrailEnabled のときだけ送る
  // Submit a new task to /api/add_task; on success clear the form, refetch the task list and close the modal after a short delay. Examples are sent only when guardrailEnabled is on
  const handlePromptSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (isPromptSubmitting) return;

      setIsPromptSubmitting(true);
      setNewPromptStatus({ message: localize("タスクを追加しています...", "Adding task…"), variant: "info" });

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
            defaultMessage: localize("タスクの追加に失敗しました。", "Could not add the task."),
            fetchImpl: resilientFetch,
          },
        );

        setNewPromptStatus({
          message:
            typeof responsePayload.message === "string" ? responsePayload.message : localize("タスクが追加されました。", "Task added."),
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
          message: error instanceof Error ? error.message : localize("エラーが発生しました。", "An error occurred."),
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
    // CSRF トークンを先に取得し、ポップアップメニューなどのカスタム要素を読み込む
    // Prime the CSRF token and load custom elements such as the popup menus
    void import("../../scripts/core/csrf").then(({ primeCsrfToken }) => {
      void primeCsrfToken();
    });
    void import("../../scripts/components/popup_menu");
    void import("../../scripts/components/chat/popup_menu");
    void import("../../scripts/components/user_icon");
  }, []);

  useIsomorphicLayoutEffect(() => {
    // ホーム画面の間だけ body に chat-page クラスを付け、離れるときに関連クラスと進行中の生成を片づける
    // Mark the body with chat-page while this screen is mounted, and on leave clear related classes and any in-flight generation
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
    // 広い画面ではサイドバーを常に開き、狭い画面（オーバーレイ表示）では閉じた状態にそろえる
    // Keep the sidebar open on wide screens and closed on narrow (overlay) ones
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

    // 表示領域の高さ・上端・ソフトキーボードが隠す量を CSS 変数に書き出す。キーボードが 24px を超えて出ているときは data-chat-keyboard-open を true にする
    // Write the visible viewport height, top offset and soft-keyboard inset to CSS variables; data-chat-keyboard-open is true when the keyboard exceeds 24px
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
    // sidebar-visible クラスは、チャット画面でオーバーレイのサイドバーが開いているときだけ付ける
    // Apply the sidebar-visible class only while an overlay sidebar is open in the chat view
    if (pageViewState !== "chat" || !sidebarOpen || !isOverlaySidebarViewport()) {
      document.body.classList.remove("sidebar-visible");
      return;
    }
    document.body.classList.add("sidebar-visible");
  }, [pageViewState, sidebarOpen]);

  useEffect(() => {
    document.body.classList.toggle("new-prompt-modal-open", isNewPromptModalOpen);
  }, [isNewPromptModalOpen]);

  // 背景のスクロールを止めるべきモーダルが開いているか
  // Whether a modal that should lock background scrolling is open
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

    // メッセージが変わるたびにスクロールを調整する。古い履歴を先頭に足した直後は読んでいた位置を保ち、そうでなければ予約があるときだけ最下部へ送る
    // Adjust scroll whenever messages change: right after older history is prepended keep the reader's position, otherwise scroll to the bottom only if requested
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

  // キャッシュ済みの認証状態はペイント前に反映する。useEffect で反映すると
  // 未ログイン状態の初期stateが一度描画され、直後に差し替わってガタつく。
  // 反映と同時にプリハイドレーション用のフラグを外し、以降はReactが表示を制御する。
  // Apply the cached auth state before the browser paints. Doing this in a
  // plain useEffect would paint the logged-out initial state once and then
  // swap it, causing a visible flash and layout shift. Releasing the
  // pre-hydration flag here hands display control back to React.
  useIsomorphicLayoutEffect(() => {
    const applyCachedAuth = consumeAuthSuccessHint();
    const cachedAuthState = readCachedAuthState();

    if (cachedAuthState !== null) {
      setLoggedIn(cachedAuthState);
      setAuthHintApplied(true);
    }

    if (applyCachedAuth && cachedAuthState === null) {
      setLoggedIn(true);
      setAuthHintApplied(true);
    }

    releaseAuthBootAttribute();
  }, [setAuthHintApplied, setLoggedIn]);

  // ログアウトを経由しないユーザー切り替え（別アカウントでの再ログインなど）を
  // 認証確認の結果から検知し、前の利用者の永続状態を画面ごと消す最後の砦。
  // 通常時（同一利用者の再訪問・初回訪問）は何もしない。
  // Detects a user switch that skipped logout (re-login as a different
  // account, etc.) from the auth check's result, and is the last line of
  // defense that wipes the previous user's persisted state along with the
  // screen. A no-op for the normal case (same user returning, or a first
  // visit).
  const applyResolvedUserScope = useCallback((userId: string | null) => {
    const { changed } = reconcileStoredUserScope(userId);
    if (!changed) return;

    setPageViewState("setup");
    setCurrentRoomId(null);
    currentRoomIdRef.current = null;
    setCurrentRoomMode("normal");
    setChatMessageListResetKey((previous) => previous + 1);
    setMessages([]);
    setHistoryHasMore(false);
    setHistoryNextBeforeId(null);
    setIsLoadingOlder(false);
  }, [
    currentRoomIdRef,
    setChatMessageListResetKey,
    setCurrentRoomId,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsLoadingOlder,
    setMessages,
    setPageViewState,
  ]);

  useEffect(() => {
    // /api/current_user でログイン状態を確定する。通信失敗など認証エラー以外では、新しいキャッシュがあればその状態を保つ
    // Confirm the login state via /api/current_user; on failures other than auth errors, keep the state if a fresh cache exists
    const canFallback = isCachedAuthStateFresh() && readCachedAuthState() !== null;

    let cancelled = false;

    resilientFetch("/api/current_user", { credentials: "same-origin" })
      .then(async (response) => {
        // readCurrentUserLoggedIn は本文を読み切るため、確認済みのユーザー ID をスコープ判定に使えるよう、複製を別に読む。既存の判定処理には触れない。
        // readCurrentUserLoggedIn consumes the body; read a clone separately so
        // the confirmed user id is available for the scope check below without
        // disturbing that existing parsing.
        const userIdProbe = response.clone();
        const nextLoggedIn = await readCurrentUserLoggedIn(response);
        const userId = nextLoggedIn ? await readCurrentUserIdFromResponse(userIdProbe) : null;
        return { nextLoggedIn, userId };
      })
      .then(({ nextLoggedIn, userId }) => {
        if (cancelled) return;
        writeCachedAuthState(nextLoggedIn);
        setLoggedIn(nextLoggedIn);
        applyResolvedUserScope(userId);
      })
      .catch((error) => {
        if (cancelled) return;
        if (error instanceof CurrentUserAuthError) {
          writeCachedAuthState(false);
          setLoggedIn(false);
          // セッション切れもユーザー不在という点ではログアウトと同じ。前の利用者の
          // 永続状態を、次の訪問者に見せないよう破棄する。
          // An expired session is, for this purpose, the same as no user: wipe
          // the previous user's persisted state so the next visitor never sees it.
          applyResolvedUserScope(null);
          showToast(
            error.status === 401
              ? localize("ログインセッションが切れました。再ログインしてください。", "Your session expired. Please log in again.")
              : localize("認証状態を確認できませんでした。再ログインしてください。", "We could not verify your account. Please log in again."),
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
  }, [applyResolvedUserScope]);

  useEffect(() => {
    // ログイン状態をアプリ共通の状態へ同期する
    // Sync the login state into the shared app state
    setLoggedInState(loggedIn);
  }, [loggedIn]);

  useEffect(() => {
    if (!cachedChatRoomsPage) return;
    const nextRooms = cachedChatRoomsPage.rooms;
    const hasPaginated = hasLoadedMoreChatRoomsRef.current;
    setChatRooms((previous) =>
      hasPaginated ? mergeUniqueChatRooms(nextRooms, previous) : nextRooms,
    );
    // 1 ページ目のバックグラウンド再検証（フォーカス復帰、ルームの変更など）で、ユーザーが追加ページまで読み込んだあとにカーソルを巻き戻してはいけない。巻き戻すと次のスクロールで表示済みのルームを再取得し、一覧が止まって見える。1 ページ目にいる間だけ、そのカーソルを採用する。
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
    // 認証が確定したらタスクを取得する。未ログインならルーム一覧に関する状態も空に戻す
    // Fetch tasks once auth is resolved; when logged out, also clear the room-list state
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

  // 保存されているビューとアクティブルームを復元する。メッセージ本文は復元せず、チャット履歴はサーバーから読み直す
  // Restore the stored view and active room; message text is not restored here and chat history is reloaded from the server
  const restoreHomeViewFromStorage = useCallback(() => {
    try {
      // 認証確認（/api/current_user）はこの後に非同期で走る。どれだけ厳しい
      // ヒューリスティックを積んでも、ログアウトを経由しないユーザー切替
      // （別アカウントでの再ログインなど）はローカルストレージの中身だけでは
      // 判別できない。したがって本文（メッセージ）は絶対にここで描画せず、
      // 常にサーバーからの loadChatHistory の応答を待つ。ここで即時復元して
      // よいのは、部屋の選択やビュー状態など機微でないレイアウトだけ。
      // The auth check (/api/current_user) only resolves later, asynchronously.
      // No amount of localStorage heuristics can distinguish a user switch
      // that skips logout (re-login as a different account, etc.) from the
      // same user returning, so message TEXT is never painted here — it
      // always waits for the server's loadChatHistory response. Only
      // non-sensitive layout (which room/view was active) is safe to restore
      // instantly here.
      const activeGeneration = readActiveStoredGenerationState();
      const storedViewState = activeGeneration ? "chat" : readRestorableHomePageViewState();
      if (activeGeneration) {
        setCurrentRoomId(activeGeneration.roomId);
        currentRoomIdRef.current = activeGeneration.roomId;
        setCurrentRoomMode(activeGeneration.roomMode);
        setPageViewState("chat");
        // 復元時はローカル履歴を末尾アンカリングしたいので、一覧を新規マウントさせる。
        // key は currentRoomId に依存しなくなったため、ここで明示的に reset する。
        setChatMessageListResetKey((previous) => previous + 1);
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
      // localStorage の失敗は無視する
      // ignore localStorage failures
    }
  }, [
    loadChatHistory,
    setCurrentRoomId,
    setChatMessageListResetKey,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsLoadingOlder,
    setMessages,
    setPageViewState,
  ]);

  // 前回のビュー（チャット画面など）とアクティブルームの復元。最初のペイント前に
  // 反映しないとセットアップ画面が一瞬表示されてからチャット画面へ切り替わるため、
  // layout effect で同期的に復元する（ローカル履歴の読み込みも同じパスで行われ、
  // 初回描画にメッセージが含まれる）。
  // Restore the previous view (e.g. chat) and active room. This must run before
  // the first paint — otherwise the setup view flashes briefly and then swaps to
  // the chat view — so restore synchronously in a layout effect (local history
  // loads on the same path, so the first paint already contains the messages).
  useIsomorphicLayoutEffect(() => {
    restoreHomeViewFromStorage();
  }, [restoreHomeViewFromStorage]);

  useEffect(() => {
    // bfcache からの復帰や戻る操作でホームに戻ったときも、同じ復元を行う
    // Run the same restoration when returning to home via bfcache or back navigation
    const restoreIfHomePage = () => {
      if (!["/", "/en", "/en/"].includes(window.location.pathname)) return;
      restoreHomeViewFromStorage();
    };

    window.addEventListener("pageshow", restoreIfHomePage);
    window.addEventListener("popstate", restoreIfHomePage);

    return () => {
      window.removeEventListener("pageshow", restoreIfHomePage);
      window.removeEventListener("popstate", restoreIfHomePage);
    };
  }, [restoreHomeViewFromStorage]);

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
    // メニューの外をクリックしたときに、モデル選択・ルーム操作メニュー・オーバーレイのサイドバーを閉じる
    // Close the model menus, room actions menu and overlay sidebar when clicking outside them
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
      // 幅が変わったときだけ本当のリサイズとみなし、画面キーボードの開閉による高さだけの変化は無視する。
      // Only treat width changes as a real resize; ignore height-only changes
      // caused by the on-screen keyboard opening/closing.
      if (Math.abs(nextWidth - lastWidth) >= 1) {
        lastWidth = nextWidth;
        closeOverlaySidebar();
        scheduleSetupViewportFit();
      }
    };
    const onVisualViewportResize = () => {
      // 表示領域が変わったらセットアップ画面の密度を再計算するが、ソフトキーボードが出るたびにちらつくので、サイドバーは自動では閉じない。
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

    // Escape で新規タスクモーダルまたは共有モーダルを閉じる。タスク送信中は閉じない
    // Close the new-task or share modal on Escape, except while the task is being submitted
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
    // AI 補助（prompt assist）を一度だけ初期化する。必要な DOM がそろうまでは何もしない
    // Initialize AI assistance (prompt assist) exactly once; do nothing until the required DOM elements exist
    if (promptAssistControllerRef.current) return;
    if (!newPromptAssistRootRef.current) return;
    if (!titleInputRef.current || !contentInputRef.current || !inputExampleRef.current || !outputExampleRef.current) {
      return;
    }

    const controller = initPromptAssist({
      root: newPromptAssistRootRef.current,
      target: "task_modal",
      fields: {
        title: { label: localize("タイトル", "Title"), element: titleInputRef.current, setValue: setNewPromptTitle },
        prompt_content: { label: localize("プロンプト内容", "Prompt content"), element: contentInputRef.current, setValue: setNewPromptContent },
        input_examples: { label: localize("入力例", "Input example"), element: inputExampleRef.current, setValue: setNewPromptInputExample },
        output_examples: { label: localize("出力例", "Output example"), element: outputExampleRef.current, setValue: setNewPromptOutputExample },
      },
      beforeApplyField: (fieldName) => {
        if (fieldName === "input_examples" || fieldName === "output_examples") {
          setGuardrailEnabled(true);
        }
      },
    });

    promptAssistControllerRef.current = (controller || null) as PromptAssistController | null;
    // モーダルは ModalShell 経由でマウントされ、初回コミット時は自身の
    // useEffect(() => setMounted(true), []) がまだ走っていないため
    // newPromptAssistRootRef 等は null のままこの effect が空振りする。
    // isNewPromptModalOpen を依存に加え、モーダルを開くたびに再試行することで
    // ref が揃った後の初期化を保証する（promptAssistControllerRef の
    // ガードにより二重初期化はしない）。
    // The modal mounts through ModalShell, whose own
    // useEffect(() => setMounted(true), []) has not run yet on this effect's
    // first commit, so newPromptAssistRootRef and the field refs are still
    // null and this effect no-ops. Re-running it every time the modal opens
    // (via isNewPromptModalOpen) guarantees it retries once the refs are
    // populated; the promptAssistControllerRef guard above prevents a second
    // initialization.
  }, [isNewPromptModalOpen]);

  useEffect(() => {
    // 入力を編集したら、直前のエラー表示を消す
    // Clear the previous error message once the user edits the inputs
    if (newPromptStatus.variant === "error") {
      setNewPromptStatus({ message: "", variant: "info" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newPromptTitle, newPromptContent, newPromptInputExample, newPromptOutputExample]);


  return {
    loggedIn,
    authResolved,
    // 右上の認証UIはサーバー確認を待たずキャッシュ反映時点で描画してよい。
    // 待つと一瞬だけ何も表示されず、後からポップインして見える。
    // The top-right auth UI can render as soon as the cached state is applied.
    // Waiting for the server leaves the corner briefly empty, then pops in.
    authDisplayReady: authResolved || authHintApplied,
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
    personalKnowledgeEnabled,
    setPersonalKnowledgeEnabled,
    sharedPromptsEnabled,
    setSharedPromptsEnabled,
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
    launchingTaskId,
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
    handleToggleRoomPin,
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
    applyToolApproval,
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
