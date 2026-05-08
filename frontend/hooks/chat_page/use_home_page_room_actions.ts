import {
  useCallback,
  type Dispatch,
  type KeyboardEvent as ReactKeyboardEvent,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import type { KeyedMutator } from "swr";

import { MAX_CHAT_MESSAGE_LENGTH, MAX_SETUP_INFO_LENGTH } from "../../lib/chat_page/constants";
import type { ChatRoom, ChatRoomMode, NormalizedTask, UiChatMessage } from "../../lib/chat_page/types";
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
  generateResponse: (message: string, model: string, roomId: string) => Promise<void>;
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
  setChatInput: Dispatch<SetStateAction<string>>;
  setChatRooms: Dispatch<SetStateAction<ChatRoom[]>>;
  setCurrentRoomMode: Dispatch<SetStateAction<ChatRoomMode>>;
  setHistoryHasMore: Dispatch<SetStateAction<boolean>>;
  setHistoryNextBeforeId: Dispatch<SetStateAction<number | null>>;
  setIsLoadingOlder: Dispatch<SetStateAction<boolean>>;
  setLaunchingTaskName: Dispatch<SetStateAction<string | null>>;
  setMessages: Dispatch<SetStateAction<UiChatMessage[]>>;
  setOpenRoomActionsFor: Dispatch<SetStateAction<string | null>>;
  setPageViewState: Dispatch<SetStateAction<PageViewState>>;
  setSetupInfo: Dispatch<SetStateAction<string>>;
  setShareStatus: (status: ShareStatus) => void;
  setShareUrl: Dispatch<SetStateAction<string>>;
};

export function useHomePageRoomActions({
  cachedChatRooms,
  chatInput,
  chatRooms,
  closeOverlaySidebar,
  closeShareModal,
  createNewChatRoom,
  currentRoomIdRef,
  fetchChatRooms,
  generateResponse,
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
  setChatInput,
  setChatRooms,
  setCurrentRoomMode,
  setHistoryHasMore,
  setHistoryNextBeforeId,
  setIsLoadingOlder,
  setLaunchingTaskName,
  setMessages,
  setOpenRoomActionsFor,
  setPageViewState,
  setSetupInfo,
  setShareStatus,
  setShareUrl,
}: UseHomePageRoomActionsParams) {
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

      setMessages([]);
      persistCurrentRoomId(null);
      setCurrentRoomMode("normal");
      setHistoryHasMore(false);
      setHistoryNextBeforeId(null);
      setIsLoadingOlder(false);
    } catch (error) {
      console.error("ルーム一覧取得失敗:", error);
      if (!activeRoomId) {
        setMessages([]);
        persistCurrentRoomId(null);
        setCurrentRoomMode("normal");
        setHistoryHasMore(false);
        setHistoryNextBeforeId(null);
        setIsLoadingOlder(false);
      }
    }
  }, [
    chatRooms,
    closeOverlaySidebar,
    currentRoomIdRef,
    loadChatRooms,
    loadLocalChatHistory,
    persistCurrentRoomId,
    prepareChatViewTransition,
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
    persistCurrentRoomId(null);
    setCurrentRoomMode("normal");
    setMessages([]);
    setShareUrl("");
    setShareStatus({ message: "共有するチャットルームを選択してください。", error: false });
    showSetupForm();
  }, [persistCurrentRoomId, showSetupForm]);

  const resetLaunchingRoomState = useCallback((roomId: string, roomMode: ChatRoomMode) => {
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
  }, [closeOverlaySidebar, persistCurrentRoomId, prepareChatViewTransition, setPageViewState]);

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
        removeStoredHistory(roomId);
        const generationPromise = generateResponse(firstMessage, selectedModel, roomId);
        setPageViewState("chat");
        setLaunchingTaskName(null);

        void loadChatRooms();
        await generationPromise;
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
      closeOverlaySidebar,
      createNewChatRoom,
      generateResponse,
      isTaskOrderEditing,
      loadChatRooms,
      persistCurrentRoomId,
      prepareChatViewTransition,
      resetLaunchingRoomState,
      selectedModel,
      setLaunchingTaskName,
      setPageViewState,
      setupInfo,
      temporaryModeEnabled,
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
      removeStoredHistory(roomId);
      const generationPromise = generateResponse(firstMessage, selectedModel, roomId);
      setPageViewState("chat");

      void loadChatRooms();
      await generationPromise;
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
    persistCurrentRoomId,
    prepareChatViewTransition,
    resetLaunchingRoomState,
    selectedModel,
    setPageViewState,
    setupInfo,
    temporaryModeEnabled,
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

    setChatInput("");
    void generateResponse(message, selectedModel, roomId);
  }, [chatInput, generateResponse, isGenerating, selectedModel, stopGeneration]);

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
          persistCurrentRoomId(null);
          setMessages([]);
          setShareUrl("");
          setShareStatus({ message: "共有するチャットルームを選択してください。", error: false });
          closeShareModal();
        }

        setOpenRoomActionsFor(null);
        void loadChatRooms();
      } catch (error) {
        showToast(`削除失敗: ${error instanceof Error ? error.message : String(error)}`, { variant: "error" });
      }
    },
    [closeShareModal, loadChatRooms, persistCurrentRoomId],
  );

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
    handleChatInputKeyDown,
    handleDeleteRoom,
    handleRenameRoom,
  };
}
