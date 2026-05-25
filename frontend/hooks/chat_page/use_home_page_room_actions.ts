import {
  useCallback,
  useRef,
  type Dispatch,
  type KeyboardEvent as ReactKeyboardEvent,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import type { KeyedMutator } from "swr";

import { MAX_CHAT_MESSAGE_LENGTH, MAX_SETUP_INFO_LENGTH } from "../../lib/chat_page/constants";
import type { AttachedFile, ChatRoom, ChatRoomMode, NormalizedTask, UiChatMessage } from "../../lib/chat_page/types";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { showToast } from "../../scripts/core/toast";
import {
  extractApiErrorMessage,
  readJsonBodySafe,
} from "../../scripts/core/runtime_validation";
import { scheduleSetupViewportFit } from "../../scripts/setup/setup_viewport";

const CHAT_LAUNCH_MIN_TRANSITION_MS = 420;

function waitForDuration(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

type ShareStatus = {
  message: string;
  error: boolean;
};

type PageViewState = "setup" | "chat" | "launching";

type UseHomePageRoomActionsParams = {
  cachedChatRooms?: ChatRoom[];
  chatInput: string;
  chatRooms: ChatRoom[];
  closeOverlaySidebar: () => void;
  closeShareModal: () => void;
  createNewChatRoom: (roomId: string, title: string, mode: ChatRoomMode) => Promise<void>;
  currentRoomIdRef: MutableRefObject<string | null>;
  fetchChatRooms: (url: string) => Promise<ChatRoom[]>;
  editAndRegenerateMessage: (newMessage: string, trailingUserCount: number, model: string, roomId: string) => Promise<void>;
  attachedFiles: AttachedFile[];
  setAttachedFiles: Dispatch<SetStateAction<AttachedFile[]>>;
  generateResponse: (
    message: string,
    model: string,
    roomId: string,
    attachedFiles?: AttachedFile[],
    roomMode?: ChatRoomMode,
  ) => Promise<boolean>;
  regenerateLastResponse: (model: string, roomId: string) => Promise<void>;
  switchBranch: (messageId: number, roomId: string) => Promise<void>;
  isGenerating: boolean;
  isTaskOrderEditing: boolean;
  loadChatHistory: (roomId: string, shouldCheckGeneration?: boolean) => Promise<void>;
  loadLocalChatHistory: (roomId: string) => void;
  loggedIn: boolean;
  mutateChatRooms: KeyedMutator<ChatRoom[]>;
  pageViewState: PageViewState;
  persistCurrentRoomId: (roomId: string | null, mode?: ChatRoomMode) => void;
  prepareChatViewTransition: () => void;
  removeStoredHistory: (roomId: string) => void;
  selectedModel: string;
  setupInfo: string;
  stopGeneration: () => Promise<void>;
  taskLaunchInProgressRef: MutableRefObject<boolean>;
  temporaryModeEnabled: boolean;
  selectedRoomIds: Set<string>;
  setChatInput: Dispatch<SetStateAction<string>>;
  setChatRooms: Dispatch<SetStateAction<ChatRoom[]>>;
  setCurrentRoomMode: Dispatch<SetStateAction<ChatRoomMode>>;
  setHistoryHasMore: Dispatch<SetStateAction<boolean>>;
  setIsBulkDeletingRooms: Dispatch<SetStateAction<boolean>>;
  setChatMessageListResetKey: Dispatch<SetStateAction<number>>;
  setHistoryNextBeforeId: Dispatch<SetStateAction<number | null>>;
  setIsLoadingOlder: Dispatch<SetStateAction<boolean>>;
  setIsRoomSelectionMode: Dispatch<SetStateAction<boolean>>;
  setLaunchingTaskName: Dispatch<SetStateAction<string | null>>;
  setMessages: Dispatch<SetStateAction<UiChatMessage[]>>;
  setOpenRoomActionsFor: Dispatch<SetStateAction<string | null>>;
  setPageViewState: Dispatch<SetStateAction<PageViewState>>;
  setSelectedRoomIds: Dispatch<SetStateAction<Set<string>>>;
  setSetupInfo: Dispatch<SetStateAction<string>>;
  setShareStatus: (status: ShareStatus) => void;
  setShareUrl: Dispatch<SetStateAction<string>>;
};

export function useHomePageRoomActions({
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
  fetchChatRooms,
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
}: UseHomePageRoomActionsParams) {
  const accessChatInProgressRef = useRef(false);

  const resetChatMessageList = useCallback(() => {
    setChatMessageListResetKey((previous) => previous + 1);
  }, [setChatMessageListResetKey]);

  const clearCurrentRoomAfterDelete = useCallback(() => {
    resetChatMessageList();
    persistCurrentRoomId(null);
    setMessages([]);
    setShareUrl("");
    setShareStatus({ message: "共有するチャットルームを選択してください。", error: false });
    closeShareModal();
  }, [closeShareModal, persistCurrentRoomId, resetChatMessageList, setMessages, setShareStatus, setShareUrl]);

  const cancelRoomSelection = useCallback(() => {
    setIsRoomSelectionMode(false);
    setSelectedRoomIds(new Set());
    setOpenRoomActionsFor(null);
  }, [setIsRoomSelectionMode, setOpenRoomActionsFor, setSelectedRoomIds]);

  const enterRoomSelectionMode = useCallback(
    (initialRoomId?: string) => {
      setIsRoomSelectionMode(true);
      setSelectedRoomIds(new Set(initialRoomId ? [initialRoomId] : []));
      setOpenRoomActionsFor(null);
    },
    [setIsRoomSelectionMode, setOpenRoomActionsFor, setSelectedRoomIds],
  );

  const toggleRoomSelection = useCallback(
    (roomId: string) => {
      setSelectedRoomIds((previous) => {
        const next = new Set(previous);
        if (next.has(roomId)) {
          next.delete(roomId);
        } else {
          next.add(roomId);
        }
        return next;
      });
    },
    [setSelectedRoomIds],
  );

  const loadChatRooms = useCallback(async (): Promise<ChatRoom[]> => {
    try {
      const rooms = loggedIn
        ? (await mutateChatRooms()) ?? cachedChatRooms ?? []
        : await fetchChatRooms("/api/get_chat_rooms");
      setChatRooms(rooms);

      const activeRoomId = currentRoomIdRef.current;
      if (activeRoomId) {
        const activeRoom = rooms.find((room) => room.id === activeRoomId);
        if (activeRoom) {
          setCurrentRoomMode(activeRoom.mode);
        }
      }
      return rooms;
    } catch (error) {
      console.error("ルーム一覧取得失敗:", error);
      return cachedChatRooms ?? [];
    }
  }, [cachedChatRooms, loggedIn, mutateChatRooms]);

  const upsertCreatedChatRoom = useCallback(
    (roomId: string, title: string, mode: ChatRoomMode) => {
      if (!loggedIn || mode !== "normal") return;

      const createdRoom: ChatRoom = {
        id: roomId,
        title: title.trim() || "新規チャット",
        createdAt: new Date().toISOString(),
        mode,
      };
      const upsert = (rooms: ChatRoom[] = []) => [
        createdRoom,
        ...rooms.filter((room) => room.id !== roomId),
      ];

      setChatRooms((previous) => upsert(previous));
      void mutateChatRooms((previous) => upsert(previous ?? cachedChatRooms ?? chatRooms), {
        revalidate: false,
      });
    },
    [cachedChatRooms, chatRooms, loggedIn, mutateChatRooms, setChatRooms],
  );

  const switchChatRoom = useCallback(
    (roomId: string, roomMode?: ChatRoomMode, options?: { forceReload?: boolean }) => {
      const forceReload = options?.forceReload === true;
      if (pageViewState !== "chat") {
        prepareChatViewTransition();
      }

      if (currentRoomIdRef.current === roomId && !forceReload) {
        setPageViewState("chat");
        closeOverlaySidebar();
        setOpenRoomActionsFor(null);
        return;
      }

      resetChatMessageList();
      const nextRoom = chatRooms.find((room) => room.id === roomId);
      if (currentRoomIdRef.current !== roomId) {
        persistCurrentRoomId(roomId, roomMode ?? nextRoom?.mode);
      }
      setCurrentRoomMode(roomMode ?? nextRoom?.mode ?? "normal");
      setPageViewState("chat");
      closeOverlaySidebar();
      setOpenRoomActionsFor(null);
      setShareStatus({ message: "共有リンクを準備しています...", error: false });
      setShareUrl("");
      loadLocalChatHistory(roomId);
      void loadChatHistory(roomId, true);
    },
    [
      chatRooms,
      closeOverlaySidebar,
      currentRoomIdRef,
      loadChatHistory,
      loadLocalChatHistory,
      pageViewState,
      persistCurrentRoomId,
      prepareChatViewTransition,
      resetChatMessageList,
      setPageViewState,
    ],
  );

  const showSetupForm = useCallback(() => {
    setPageViewState("setup");
    closeOverlaySidebar();
    setLaunchingTaskName(null);
    setSetupInfo("");
    closeShareModal();
    scheduleSetupViewportFit();
  }, [closeOverlaySidebar, closeShareModal, setLaunchingTaskName, setPageViewState]);

  const handleAccessChat = useCallback(async () => {
    if (accessChatInProgressRef.current) return;
    accessChatInProgressRef.current = true;

    try {
      const activeRoomId = currentRoomIdRef.current;
      const preferredLoadedRoom =
        (activeRoomId ? chatRooms.find((room) => room.id === activeRoomId) : null) ?? chatRooms[0] ?? null;

      if (preferredLoadedRoom) {
        switchChatRoom(preferredLoadedRoom.id, preferredLoadedRoom.mode, { forceReload: true });
        return;
      }

      prepareChatViewTransition();
      setPageViewState("chat");
      closeOverlaySidebar();
      setOpenRoomActionsFor(null);
      resetChatMessageList();

      if (activeRoomId) {
        loadLocalChatHistory(activeRoomId);
      } else {
        setMessages([]);
        setHistoryHasMore(false);
        setHistoryNextBeforeId(null);
        setIsLoadingOlder(false);
      }

      try {
        const rooms = await loadChatRooms();
        const preferredFetchedRoom =
          (activeRoomId ? rooms.find((room) => room.id === activeRoomId) : null) ?? rooms[0] ?? null;

        if (preferredFetchedRoom) {
          switchChatRoom(preferredFetchedRoom.id, preferredFetchedRoom.mode, { forceReload: true });
          return;
        }

        resetChatMessageList();
        setMessages([]);
        persistCurrentRoomId(null);
        setCurrentRoomMode("normal");
        setHistoryHasMore(false);
        setHistoryNextBeforeId(null);
        setIsLoadingOlder(false);
      } catch (error) {
        console.error("ルーム一覧取得失敗:", error);
        if (!activeRoomId) {
          resetChatMessageList();
          setMessages([]);
          persistCurrentRoomId(null);
          setCurrentRoomMode("normal");
          setHistoryHasMore(false);
          setHistoryNextBeforeId(null);
          setIsLoadingOlder(false);
        }
      }
    } finally {
      accessChatInProgressRef.current = false;
    }
  }, [
    chatRooms,
    closeOverlaySidebar,
    currentRoomIdRef,
    loadChatRooms,
    loadLocalChatHistory,
    persistCurrentRoomId,
    prepareChatViewTransition,
    resetChatMessageList,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsLoadingOlder,
    setMessages,
    setOpenRoomActionsFor,
    setPageViewState,
    switchChatRoom,
  ]);

  const handleNewChat = useCallback(() => {
    cancelRoomSelection();
    persistCurrentRoomId(null);
    setCurrentRoomMode("normal");
    setMessages([]);
    setShareUrl("");
    setShareStatus({ message: "共有するチャットルームを選択してください。", error: false });
    showSetupForm();
  }, [cancelRoomSelection, persistCurrentRoomId, showSetupForm]);

  const resetLaunchingRoomState = useCallback((roomId: string, roomMode: ChatRoomMode) => {
    resetChatMessageList();
    persistCurrentRoomId(roomId, roomMode);
    setCurrentRoomMode(roomMode);
    setMessages([]);
    setChatInput("");
    setOpenRoomActionsFor(null);
    setShareUrl("");
    setShareStatus({ message: "共有リンクを準備しています...", error: false });
    setHistoryHasMore(false);
    setHistoryNextBeforeId(null);
    setIsLoadingOlder(false);
    closeOverlaySidebar();
    prepareChatViewTransition();
    setPageViewState("launching");
  }, [closeOverlaySidebar, persistCurrentRoomId, prepareChatViewTransition, resetChatMessageList, setPageViewState]);

  const handleTaskCardLaunch = useCallback(
    async (task: NormalizedTask) => {
      if (isTaskOrderEditing) return;
      if (taskLaunchInProgressRef.current) return;

      taskLaunchInProgressRef.current = true;
      setLaunchingTaskName(task.name);

      const roomId = Date.now().toString();
      const roomMode: ChatRoomMode = temporaryModeEnabled ? "temporary" : "normal";
      const currentSetupInfo = setupInfo.trim();
      const roomTitle = (currentSetupInfo || "新規チャット").slice(0, 255);
      const firstMessage = currentSetupInfo
        ? `【タスク】${task.name}\n【状況・作業環境】${currentSetupInfo}`
        : `【タスク】${task.name}`;

      resetLaunchingRoomState(roomId, roomMode);

      try {
        await Promise.all([
          createNewChatRoom(roomId, roomTitle, roomMode),
          waitForDuration(CHAT_LAUNCH_MIN_TRANSITION_MS),
        ]);
        if (currentRoomIdRef.current !== roomId) {
          setLaunchingTaskName(null);
          return;
        }
        upsertCreatedChatRoom(roomId, roomTitle, roomMode);
        removeStoredHistory(roomId);
        const filesToSend = attachedFiles.length > 0 ? [...attachedFiles] : undefined;
        setAttachedFiles([]);
        const generationPromise = generateResponse(firstMessage, selectedModel, roomId, filesToSend, roomMode);
        setPageViewState("chat");
        setLaunchingTaskName(null);

        const completed = await generationPromise;
        if (!completed && loggedIn && roomMode === "normal") {
          void loadChatRooms();
        }
      } catch (error) {
        setPageViewState("setup");
        setLaunchingTaskName(null);
        setMessages([]);
        persistCurrentRoomId(null);
        setCurrentRoomMode("normal");
        showToast(`チャットルーム作成に失敗: ${error instanceof Error ? error.message : String(error)}`, {
          variant: "error",
        });
      } finally {
        taskLaunchInProgressRef.current = false;
      }
    },
    [
      attachedFiles,
      closeOverlaySidebar,
      createNewChatRoom,
      generateResponse,
      isTaskOrderEditing,
      loadChatRooms,
      loggedIn,
      persistCurrentRoomId,
      prepareChatViewTransition,
      resetLaunchingRoomState,
      selectedModel,
      setAttachedFiles,
      setLaunchingTaskName,
      setPageViewState,
      setupInfo,
      temporaryModeEnabled,
      upsertCreatedChatRoom,
    ],
  );

  const handleSetupSendMessage = useCallback(async () => {
    if (taskLaunchInProgressRef.current) return;

    const firstMessage = setupInfo.trim();
    if (!firstMessage) return;
    if (firstMessage.length > MAX_SETUP_INFO_LENGTH) return;

    taskLaunchInProgressRef.current = true;

    const roomId = Date.now().toString();
    const roomMode: ChatRoomMode = temporaryModeEnabled ? "temporary" : "normal";
    const roomTitle = firstMessage.slice(0, 255) || "新規チャット";

    resetLaunchingRoomState(roomId, roomMode);

    try {
      await Promise.all([
        createNewChatRoom(roomId, roomTitle, roomMode),
        waitForDuration(CHAT_LAUNCH_MIN_TRANSITION_MS),
      ]);
      if (currentRoomIdRef.current !== roomId) {
        return;
      }
      upsertCreatedChatRoom(roomId, roomTitle, roomMode);
      removeStoredHistory(roomId);
      const filesToSend = attachedFiles.length > 0 ? [...attachedFiles] : undefined;
      setAttachedFiles([]);
      const generationPromise = generateResponse(firstMessage, selectedModel, roomId, filesToSend, roomMode);
      setPageViewState("chat");

      const completed = await generationPromise;
      if (!completed && loggedIn && roomMode === "normal") {
        void loadChatRooms();
      }
    } catch (error) {
      setPageViewState("setup");
      setMessages([]);
      persistCurrentRoomId(null);
      setCurrentRoomMode("normal");
      showToast(`チャットルーム作成に失敗: ${error instanceof Error ? error.message : String(error)}`, {
        variant: "error",
      });
    } finally {
      taskLaunchInProgressRef.current = false;
    }
  }, [
    closeOverlaySidebar,
    createNewChatRoom,
    generateResponse,
    loadChatRooms,
    loggedIn,
    persistCurrentRoomId,
    prepareChatViewTransition,
    resetLaunchingRoomState,
    selectedModel,
    setPageViewState,
    setupInfo,
    temporaryModeEnabled,
    upsertCreatedChatRoom,
  ]);

  const handleSendMessage = useCallback(() => {
    if (isGenerating) {
      void stopGeneration();
      return;
    }

    const roomId = currentRoomIdRef.current;
    if (!roomId) return;

    const message = chatInput.trim();
    if (!message) return;

    if (message.length > MAX_CHAT_MESSAGE_LENGTH) return;

    const filesToSend = attachedFiles.length > 0 ? [...attachedFiles] : undefined;
    setChatInput("");
    setAttachedFiles([]);
    void generateResponse(message, selectedModel, roomId, filesToSend);
  }, [attachedFiles, chatInput, generateResponse, isGenerating, selectedModel, setAttachedFiles, stopGeneration]);

  const handleRegenerateMessage = useCallback(() => {
    if (isGenerating) return;

    const roomId = currentRoomIdRef.current;
    if (!roomId) return;

    void regenerateLastResponse(selectedModel, roomId);
  }, [isGenerating, regenerateLastResponse, selectedModel]);

  const handleEditAndRegenerateMessage = useCallback(
    (newMessage: string, trailingUserCount: number) => {
      if (isGenerating) return;
      const roomId = currentRoomIdRef.current;
      if (!roomId) return;
      void editAndRegenerateMessage(newMessage, trailingUserCount, selectedModel, roomId);
    },
    [editAndRegenerateMessage, isGenerating, selectedModel],
  );

  const handleSwitchBranch = useCallback(
    (messageId: number) => {
      if (isGenerating) return;
      const roomId = currentRoomIdRef.current;
      if (!roomId) return;
      void switchBranch(messageId, roomId);
    },
    [isGenerating, switchBranch],
  );

  const handleChatInputKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (event.nativeEvent.isComposing) return;
      if (event.key !== "Enter" || event.shiftKey) return;
      event.preventDefault();
      handleSendMessage();
    },
    [handleSendMessage],
  );

  const handleDeleteRoom = useCallback(
    async (roomId: string, roomTitle: string) => {
      const confirmed = await showConfirmModal(`「${roomTitle}」を削除しますか？`);
      if (!confirmed) return;

      try {
        const response = await fetch("/api/delete_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId }),
        });
        const payload = await readJsonBodySafe(response);

        if (!response.ok) {
          throw new Error(extractApiErrorMessage(payload, "削除失敗", response.status));
        }

        if (roomId === currentRoomIdRef.current) {
          clearCurrentRoomAfterDelete();
        }

        setOpenRoomActionsFor(null);
        void loadChatRooms();
      } catch (error) {
        showToast(`削除失敗: ${error instanceof Error ? error.message : String(error)}`, { variant: "error" });
      }
    },
    [clearCurrentRoomAfterDelete, currentRoomIdRef, loadChatRooms, setOpenRoomActionsFor],
  );

  const handleBulkDeleteRooms = useCallback(async () => {
    const roomIds = Array.from(selectedRoomIds);
    if (roomIds.length === 0) return;

    const confirmed = await showConfirmModal(`${roomIds.length}件のチャットを削除しますか？`);
    if (!confirmed) return;

    setIsBulkDeletingRooms(true);
    try {
      const response = await fetch("/api/delete_chat_rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ room_ids: roomIds }),
      });
      const payload = await readJsonBodySafe(response);

      if (!response.ok) {
        throw new Error(extractApiErrorMessage(payload, "削除失敗", response.status));
      }

      if (currentRoomIdRef.current && selectedRoomIds.has(currentRoomIdRef.current)) {
        clearCurrentRoomAfterDelete();
      }

      cancelRoomSelection();
      void loadChatRooms();
      showToast(`${roomIds.length}件のチャットを削除しました。`, { variant: "success" });
    } catch (error) {
      showToast(`削除失敗: ${error instanceof Error ? error.message : String(error)}`, { variant: "error" });
    } finally {
      setIsBulkDeletingRooms(false);
    }
  }, [
    cancelRoomSelection,
    clearCurrentRoomAfterDelete,
    currentRoomIdRef,
    loadChatRooms,
    selectedRoomIds,
    setIsBulkDeletingRooms,
  ]);

  const handleRenameRoom = useCallback(
    async (roomId: string, currentTitle: string) => {
      const nextTitle = window.prompt("新しいチャットルーム名", currentTitle);
      if (!nextTitle || !nextTitle.trim()) return;

      try {
        const response = await fetch("/api/rename_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId, new_title: nextTitle.trim() }),
        });
        const payload = await readJsonBodySafe(response);

        if (!response.ok) {
          throw new Error(extractApiErrorMessage(payload, "名前変更失敗", response.status));
        }

        setOpenRoomActionsFor(null);
        void loadChatRooms();
      } catch (error) {
        showToast(`名前変更失敗: ${error instanceof Error ? error.message : String(error)}`, { variant: "error" });
      }
    },
    [loadChatRooms],
  );

  return {
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
  };
}
