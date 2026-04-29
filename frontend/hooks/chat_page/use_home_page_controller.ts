import {
  useCallback,
  useEffect,
  useRef,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import useSWR from "swr";
import { useHomePageChatState } from "./use_home_page_chat_state";
import { useHomePageNewPromptState } from "./use_home_page_new_prompt_state";
import { useHomePageShareState } from "./use_home_page_share_state";
import { useHomePageTaskState } from "./use_home_page_task_state";
import { useHomePageUiState } from "./use_home_page_ui_state";
import { useHomePageAiAgentState } from "./use_home_page_ai_agent_state";
import { setLoggedInState } from "../../scripts/core/app_state";
import { CHAT_HISTORY_PAGE_SIZE, MAX_CHAT_MESSAGE_LENGTH, MAX_SETUP_INFO_LENGTH } from "../../lib/chat_page/constants";
import { isNearBottom } from "../../lib/chat_page/dom";
import { buildTaskOrderForPersistence } from "../../lib/chat_page/home_page_controller_utils";
import { nextMessageId } from "../../lib/chat_page/message_ids";
import { parseStreamEventBlock } from "../../lib/chat_page/streaming";
import {
  normalizeChatHistoryPayload,
  normalizeChatResponsePayload,
  normalizeChatRoomsPayload,
  normalizeGenerationStatusPayload,
  normalizeShareChatRoomPayload,
} from "../../lib/chat_page/api_contract";
import {
  appendStoredHistory,
  consumeAuthSuccessHint,
  isCachedAuthStateFresh,
  normalizeHistorySender,
  normalizeStoredSender,
  prependStoredHistory,
  readCachedAuthState,
  readStoredHistory,
  removeStoredHistory,
  toStoredSender,
  writeCachedAuthState,
  writeStoredHistory,
} from "../../lib/chat_page/storage";
import { FALLBACK_TASKS, normalizeTaskList } from "../../lib/chat_page/task_utils";
import type {
  ChatHistoryPagination,
  ChatRoom,
  ChatRoomMode,
  NormalizedTask,
  PromptAssistController,
  UiChatMessage,
} from "../../lib/chat_page/types";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { STORAGE_KEYS } from "../../scripts/core/constants";
import { showToast } from "../../scripts/core/toast";
import {
  extractApiErrorMessage,
  fetchJsonOrThrow,
  readJsonBodySafe,
} from "../../scripts/core/runtime_validation";
import { copyTextToClipboard } from "../../scripts/chat/message_utils";
import { initPromptAssist } from "../../scripts/components/prompt_assist";
import type { TaskItem } from "../../scripts/setup/setup_types";
import {
  invalidateTasksCache,
  readCachedTasks,
  writeCachedTasks,
} from "../../scripts/setup/setup_tasks_cache";
import { bindSetupViewportFit, scheduleSetupViewportFit } from "../../scripts/setup/setup_viewport";

const CHAT_LAUNCH_MIN_TRANSITION_MS = 420;

const fetchChatRooms = async (url: string): Promise<ChatRoom[]> => {
  const response = await fetch(url, { credentials: "same-origin" });
  const rawPayload = await readJsonBodySafe(response);
  const payload = normalizeChatRoomsPayload(rawPayload);

  if (!response.ok || payload.error) {
    throw new Error(extractApiErrorMessage(rawPayload, "ルーム一覧取得に失敗しました。", response.status));
  }

  return payload.rooms;
};

function waitForDuration(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

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
    currentRoomId,
    setCurrentRoomId,
    currentRoomMode,
    setCurrentRoomMode,
    messages,
    setMessages,
    chatInput,
    setChatInput,
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

  const draggingTaskIndexRef = useRef<number | null>(null);
  const trackedTimeoutIdsRef = useRef<Set<number>>(new Set());
  const hasCurrentRoom = Boolean(currentRoomId);
  const { data: cachedChatRooms, mutate: mutateChatRooms } = useSWR<ChatRoom[]>(
    loggedIn ? "/api/get_chat_rooms" : null,
    fetchChatRooms,
    {
      revalidateOnFocus: true,
      dedupingInterval: 5000,
      keepPreviousData: true,
    },
  );

  const scheduleAutoScrollIfNeeded = useCallback((force = false) => {
    const container = chatMessagesRef.current;
    if (!container) {
      pendingAutoScrollRef.current = true;
      return;
    }
    if (force || isNearBottom(container)) {
      pendingAutoScrollRef.current = true;
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

  const disconnectActiveGeneration = useCallback(() => {
    const abortController = abortControllerRef.current;
    if (!abortController) return;
    abortController.abort();
    abortControllerRef.current = null;
    setIsGenerating(false);
  }, []);

  const persistCurrentRoomId = useCallback((roomId: string | null, mode?: ChatRoomMode) => {
    if (currentRoomIdRef.current !== roomId) {
      disconnectActiveGeneration();
    }
    currentRoomIdRef.current = roomId;
    setCurrentRoomId(roomId);
    try {
      if (roomId && mode !== "temporary") {
        localStorage.setItem(STORAGE_KEYS.currentChatRoomId, roomId);
      } else {
        localStorage.removeItem(STORAGE_KEYS.currentChatRoomId);
      }
    } catch {
      // ignore localStorage failures
    }
  }, [disconnectActiveGeneration]);

  const removeThinkingMessages = useCallback((list: UiChatMessage[]) => {
    return list.filter((message) => message.sender !== "thinking");
  }, []);

  const appendAssistantErrorMessage = useCallback(
    (roomId: string, errorMessage: string) => {
      const id = nextMessageId("assistant-error", messageSeqRef);
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId) return previous;
        return [
          ...removeThinkingMessages(previous),
          {
            id,
            sender: "assistant",
            text: `エラー: ${errorMessage}`,
            error: true,
          },
        ];
      });
      scheduleAutoScrollIfNeeded(true);
    },
    [removeThinkingMessages, scheduleAutoScrollIfNeeded],
  );

  const saveUiMessagesToLocalStorage = useCallback((roomId: string, uiMessages: UiChatMessage[]) => {
    const normalized = uiMessages
      .filter((message) => message.sender === "user" || message.sender === "assistant")
      .map((message) => ({
        text: message.text,
        sender: toStoredSender(message.sender),
      }));
    writeStoredHistory(roomId, normalized);
  }, []);

  const loadLocalChatHistory = useCallback(
    (roomId: string) => {
      const localEntries = readStoredHistory(roomId);
      const localMessages: UiChatMessage[] = localEntries.map((entry) => ({
        id: nextMessageId("local", messageSeqRef),
        sender: normalizeStoredSender(entry.sender),
        text: entry.text,
      }));

      setMessages(localMessages);
      setHistoryHasMore(false);
      setHistoryNextBeforeId(null);
      scheduleAutoScrollIfNeeded(true);
    },
    [scheduleAutoScrollIfNeeded],
  );

  const fetchChatHistoryPage = useCallback(async (roomId: string, beforeId?: number | null) => {
    const params = new URLSearchParams({
      room_id: roomId,
      limit: String(CHAT_HISTORY_PAGE_SIZE),
    });
    if (typeof beforeId === "number") {
      params.set("before_id", String(beforeId));
    }

    const response = await fetch(`/api/get_chat_history?${params.toString()}`, {
      credentials: "same-origin",
    });
    const rawPayload = await readJsonBodySafe(response);
    const payload = normalizeChatHistoryPayload(rawPayload);

    if (!response.ok || payload.error) {
      throw new Error(extractApiErrorMessage(rawPayload, "履歴取得に失敗しました。", response.status));
    }

    const normalizedPagination: ChatHistoryPagination = {
      hasMore: payload.pagination.hasMore,
      nextBeforeId: payload.pagination.nextBeforeId,
    };

    return {
      messages: payload.messages,
      pagination: normalizedPagination,
      roomMode: payload.roomMode,
    };
  }, []);

  const consumeStreamingChatResponse = useCallback(
    async (response: Response, roomId: string) => {
      if (!response.body) {
        throw new Error("ストリーム応答を受信できませんでした。");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      let streamError: string | null = null;
      let streamingMessageId: string | null = null;
      let streamedText = "";

      const ensureStreamingMessage = () => {
        if (streamingMessageId) return streamingMessageId;
        streamingMessageId = nextMessageId("assistant-stream", messageSeqRef);
        const newId = streamingMessageId;

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId) return previous;
          return [
            ...removeThinkingMessages(previous),
            {
              id: newId,
              sender: "assistant",
              text: "",
              streaming: true,
            },
          ];
        });
        scheduleAutoScrollIfNeeded();
        return newId;
      };

      const finalizeStreamingMessage = (finalText: string, persist = true) => {
        if (!streamingMessageId) {
          if (finalText) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId) return previous;
              return [
                ...removeThinkingMessages(previous),
                {
                  id: nextMessageId("assistant", messageSeqRef),
                  sender: "assistant",
                  text: finalText,
                },
              ];
            });
          } else {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId) return previous;
              return removeThinkingMessages(previous);
            });
          }
          if (persist && finalText) {
            appendStoredHistory(roomId, { text: finalText, sender: "bot" });
          }
          scheduleAutoScrollIfNeeded(true);
          return;
        }

        const streamId = streamingMessageId;
        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId) return previous;
          return removeThinkingMessages(previous).map((message) => {
            if (message.id !== streamId) return message;
            return {
              ...message,
              text: finalText || message.text,
              streaming: false,
            };
          });
        });

        if (persist && finalText) {
          appendStoredHistory(roomId, { text: finalText, sender: "bot" });
        }
        scheduleAutoScrollIfNeeded(true);
      };

      const processBlock = (block: string) => {
        const parsed = parseStreamEventBlock(block);
        if (!parsed) return;

        if (typeof parsed.id === "number" && parsed.id > 0) {
          streamLastEventIdByRoomRef.current.set(roomId, parsed.id);
        }

        if (parsed.event === "chunk") {
          const text = typeof parsed.data.text === "string" ? parsed.data.text : "";
          if (!text) return;
          const streamId = ensureStreamingMessage();
          streamedText += text;

          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId) return previous;
            return previous.map((message) => {
              if (message.id !== streamId) return message;
              return {
                ...message,
                text: streamedText,
                streaming: true,
              };
            });
          });
          scheduleAutoScrollIfNeeded();
          return;
        }

        if (parsed.event === "done") {
          completed = true;
          const responseText = typeof parsed.data.response === "string" ? parsed.data.response : streamedText;
          finalizeStreamingMessage(responseText, true);
          streamLastEventIdByRoomRef.current.delete(roomId);
          return;
        }

        if (parsed.event === "aborted") {
          completed = true;
          finalizeStreamingMessage(streamedText, false);
          return;
        }

        if (parsed.event === "error") {
          streamError =
            typeof parsed.data.message === "string"
              ? parsed.data.message
              : "ストリーミング生成中にエラーが発生しました。";
        }
      };

      try {
        while (true) {
          const { value, done } = await reader.read();
          buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

          const blocks = buffer.split(/\r?\n\r?\n/);
          buffer = blocks.pop() || "";
          blocks.forEach(processBlock);

          if (streamError) break;
          if (done) break;
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          finalizeStreamingMessage(streamedText, false);
          return;
        }
        throw error;
      } finally {
        reader.cancel().catch(() => {
          // no-op
        });
      }

      if (streamError) {
        if (streamedText) {
          finalizeStreamingMessage(streamedText, false);
        } else {
          appendAssistantErrorMessage(roomId, streamError);
        }
        return;
      }

      if (!completed) {
        appendAssistantErrorMessage(roomId, "ストリームが途中で終了しました。");
      }
    },
    [appendAssistantErrorMessage, removeThinkingMessages, scheduleAutoScrollIfNeeded],
  );

  const connectToGenerationStream = useCallback(
    async (roomId: string) => {
      if (abortControllerRef.current) return;

      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      setIsGenerating(true);

      const thinkingId = nextMessageId("thinking", messageSeqRef);
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId) return previous;
        return [
          ...removeThinkingMessages(previous),
          {
            id: thinkingId,
            sender: "thinking",
            text: "",
          },
        ];
      });

      const headers: Record<string, string> = {};
      const lastEventId = streamLastEventIdByRoomRef.current.get(roomId);
      if (typeof lastEventId === "number" && lastEventId > 0) {
        headers["Last-Event-ID"] = String(lastEventId);
      }

      try {
        const response = await fetch(`/api/chat_generation_stream?room_id=${encodeURIComponent(roomId)}`, {
          credentials: "same-origin",
          signal: abortController.signal,
          headers,
        });

        if (!response.ok) {
          const rawPayload = await readJsonBodySafe(response);
          appendAssistantErrorMessage(
            roomId,
            extractApiErrorMessage(rawPayload, "チャットの応答取得に失敗しました。", response.status),
          );
          return;
        }

        await consumeStreamingChatResponse(response, roomId);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          appendAssistantErrorMessage(
            roomId,
            error instanceof Error ? error.message : "チャットの応答取得に失敗しました。",
          );
        }
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
          setIsGenerating(false);
        }
      }
    },
    [appendAssistantErrorMessage, consumeStreamingChatResponse],
  );

  const loadChatHistory = useCallback(
    async (roomId: string, shouldCheckGeneration = true) => {
      try {
        const { messages: historyMessages, pagination, roomMode } = await fetchChatHistoryPage(roomId);
        if (currentRoomIdRef.current !== roomId) return;

        const uiMessages: UiChatMessage[] = historyMessages.map((entry) => ({
          id: nextMessageId("history", messageSeqRef),
          sender: normalizeHistorySender(entry.sender),
          text: typeof entry.message === "string" ? entry.message : "",
        }));

        setCurrentRoomMode(roomMode);
        setHistoryHasMore(pagination.hasMore);
        setHistoryNextBeforeId(pagination.nextBeforeId);

        if (!shouldCheckGeneration) {
          setMessages(uiMessages);
          saveUiMessagesToLocalStorage(roomId, uiMessages);
          scheduleAutoScrollIfNeeded(true);
          return;
        }

        let generationStatus = normalizeGenerationStatusPayload({});
        try {
          const statusResponse = await fetch(`/api/chat_generation_status?room_id=${encodeURIComponent(roomId)}`, {
            credentials: "same-origin",
          });
          generationStatus = normalizeGenerationStatusPayload(await readJsonBodySafe(statusResponse));
        } catch {
          generationStatus = normalizeGenerationStatusPayload({});
        }

        if (currentRoomIdRef.current !== roomId) return;

        if (generationStatus.is_generating) {
          setMessages(uiMessages);
          saveUiMessagesToLocalStorage(roomId, uiMessages);
          scheduleAutoScrollIfNeeded(true);
          void connectToGenerationStream(roomId);
          return;
        }

        if (generationStatus.has_replayable_job) {
          let lastAssistantIndex = -1;
          for (let i = uiMessages.length - 1; i >= 0; i -= 1) {
            if (uiMessages[i]?.sender === "assistant") {
              lastAssistantIndex = i;
              break;
            }
          }

          const replayBaseMessages =
            lastAssistantIndex >= 0
              ? [...uiMessages.slice(0, lastAssistantIndex), ...uiMessages.slice(lastAssistantIndex + 1)]
              : uiMessages;

          setMessages(replayBaseMessages);
          saveUiMessagesToLocalStorage(roomId, replayBaseMessages);
          scheduleAutoScrollIfNeeded(true);
          void connectToGenerationStream(roomId);
          return;
        }

        setMessages(uiMessages);
        saveUiMessagesToLocalStorage(roomId, uiMessages);
        scheduleAutoScrollIfNeeded(true);
      } catch (error) {
        console.error("履歴取得失敗:", error);
      }
    },
    [connectToGenerationStream, fetchChatHistoryPage, saveUiMessagesToLocalStorage, scheduleAutoScrollIfNeeded],
  );

  const loadOlderChatHistory = useCallback(async () => {
    const roomId = currentRoomIdRef.current;
    if (!roomId) return;
    if (!historyHasMore) return;
    if (historyNextBeforeId === null) return;
    if (isLoadingOlder) return;

    const container = chatMessagesRef.current;
    if (!container) return;

    setIsLoadingOlder(true);
    prependScrollRestoreRef.current = {
      prevScrollHeight: container.scrollHeight,
      prevScrollTop: container.scrollTop,
    };

    try {
      const { messages: olderMessages, pagination } = await fetchChatHistoryPage(roomId, historyNextBeforeId);
      if (currentRoomIdRef.current !== roomId) return;

      const uiMessages = olderMessages.map((entry) => ({
        id: nextMessageId("history-older", messageSeqRef),
        sender: normalizeHistorySender(entry.sender),
        text: typeof entry.message === "string" ? entry.message : "",
      }));

      setMessages((previous) => [...uiMessages, ...previous]);
      setHistoryHasMore(pagination.hasMore);
      setHistoryNextBeforeId(pagination.nextBeforeId);

      prependStoredHistory(
        roomId,
        uiMessages
          .filter((message) => message.sender === "user" || message.sender === "assistant")
          .map((message) => ({ text: message.text, sender: toStoredSender(message.sender) })),
      );
    } catch (error) {
      console.error("追加履歴取得失敗:", error);
      prependScrollRestoreRef.current = null;
    } finally {
      setIsLoadingOlder(false);
    }
  }, [fetchChatHistoryPage, historyHasMore, historyNextBeforeId, isLoadingOlder]);

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

      if (currentRoomIdRef.current === roomId && !forceReload) {
        setPageViewState("chat");
        setSidebarOpen(false);
        setOpenRoomActionsFor(null);
        return;
      }

      const nextRoom = chatRooms.find((room) => room.id === roomId);
      if (currentRoomIdRef.current !== roomId) {
        persistCurrentRoomId(roomId, roomMode ?? nextRoom?.mode);
      }
      setCurrentRoomMode(roomMode ?? nextRoom?.mode ?? "normal");
      setPageViewState("chat");
      setSidebarOpen(false);
      setOpenRoomActionsFor(null);
      setShareStatus({ message: "共有リンクを準備しています...", error: false });
      setShareUrl("");
      loadLocalChatHistory(roomId);
      void loadChatHistory(roomId, true);
    },
    [chatRooms, currentRoomIdRef, loadChatHistory, loadLocalChatHistory, persistCurrentRoomId, setPageViewState],
  );

  const createNewChatRoom = useCallback(async (roomId: string, title: string, mode: ChatRoomMode) => {
    const response = await fetch("/api/new_chat_room", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ id: roomId, title, mode }),
    });

    const payload = (await readJsonBodySafe(response)) as { error?: string };
    if (!response.ok || payload.error) {
      throw new Error(extractApiErrorMessage(payload, "チャットルーム作成に失敗しました。", response.status));
    }
  }, []);

  const generateResponse = useCallback(
    async (message: string, model: string, roomId: string) => {
      if (abortControllerRef.current) return;

      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      setIsGenerating(true);

      const userMessage: UiChatMessage = {
        id: nextMessageId("user", messageSeqRef),
        sender: "user",
        text: message,
      };
      const thinkingMessage: UiChatMessage = {
        id: nextMessageId("thinking", messageSeqRef),
        sender: "thinking",
        text: "",
      };

      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId) return previous;
        return [...removeThinkingMessages(previous), userMessage, thinkingMessage];
      });
      appendStoredHistory(roomId, { text: message, sender: "user" });
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      scheduleAutoScrollIfNeeded(true);

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            message,
            chat_room_id: roomId,
            model,
          }),
          signal: abortController.signal,
        });

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          await consumeStreamingChatResponse(response, roomId);
          return;
        }

        const rawPayload = await readJsonBodySafe(response);
        const data = normalizeChatResponsePayload(rawPayload);

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId) return previous;
          const trimmed = removeThinkingMessages(previous);

          if (response.ok && data.response) {
            return [
              ...trimmed,
              {
                id: nextMessageId("assistant", messageSeqRef),
                sender: "assistant",
                text: data.response,
              },
            ];
          }

          return [
            ...trimmed,
            {
              id: nextMessageId("assistant-error", messageSeqRef),
              sender: "assistant",
              text: `エラー: ${extractApiErrorMessage(rawPayload, "予期しないエラーが発生しました。", response.status)}`,
              error: true,
            },
          ];
        });

        if (response.ok && data.response) {
          appendStoredHistory(roomId, { text: data.response, sender: "bot" });
        }
        scheduleAutoScrollIfNeeded(true);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId) return previous;
            return removeThinkingMessages(previous);
          });
          return;
        }

        const errorMessage = error instanceof Error ? error.message : String(error);
        appendAssistantErrorMessage(roomId, errorMessage);
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
          setIsGenerating(false);
        }
      }
    },
    [appendAssistantErrorMessage, consumeStreamingChatResponse, removeThinkingMessages, scheduleAutoScrollIfNeeded],
  );

  const stopGeneration = useCallback(async () => {
    const roomId = currentRoomIdRef.current;
    disconnectActiveGeneration();
    if (!roomId) return;

    try {
      await fetch("/api/chat_stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ chat_room_id: roomId }),
      });
    } catch {
      // best effort
    }
  }, [disconnectActiveGeneration]);

  const refreshTasks = useCallback(
    async (forceRefresh = false) => {
      if (!forceRefresh) {
        const cached = readCachedTasks();
        if (Array.isArray(cached) && cached.length > 0) {
          setTasks(normalizeTaskList(cached));
          return;
        }
      }

      setTasks(FALLBACK_TASKS);

      try {
        const { payload } = await fetchJsonOrThrow<{ tasks?: TaskItem[] }>("/api/tasks", undefined, {
          defaultMessage: "タスクの読み込みに失敗しました。",
        });

        const fetchedTasks = Array.isArray(payload.tasks) ? payload.tasks : [];
        if (fetchedTasks.length > 0) {
          writeCachedTasks(fetchedTasks);
        }

        setTasks(normalizeTaskList(fetchedTasks));
      } catch (error) {
        console.error("タスク読み込みに失敗:", error);
        setTasks(FALLBACK_TASKS);
      }
    },
    [],
  );

  const saveTaskOrder = useCallback(async (nextTasks: NormalizedTask[]) => {
    const order = buildTaskOrderForPersistence(nextTasks);

    if (order.length === 0) return;

    try {
      await fetchJsonOrThrow("/api/update_tasks_order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ order }),
      });
      invalidateTasksCache();
    } catch (error) {
      const message = error instanceof Error ? error.message : "並び順の保存に失敗しました。";
      showToast(`並び順の保存に失敗: ${message}`, { variant: "error" });
    }
  }, []);

  const closeShareModal = useCallback(() => {
    setShareModalOpen(false);
  }, []);

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

  const setShareActionLoading = useCallback((loading: boolean) => {
    setShareLoading(loading);
  }, []);

  const createShareLink = useCallback(
    async (forceRefresh = false) => {
      const roomId = currentRoomIdRef.current;
      if (!roomId) {
        setShareStatus({ message: "共有するチャットルームを選択してください。", error: true });
        setShareUrl("");
        return;
      }
      if (currentRoomMode === "temporary") {
        setShareStatus({ message: "未保存チャットは共有できません。", error: true });
        setShareUrl("");
        return;
      }

      if (!forceRefresh && shareCacheRef.current.has(roomId)) {
        const cached = shareCacheRef.current.get(roomId) || "";
        setShareUrl(cached);
        setShareStatus({ message: "共有リンクを表示しています。", error: false });
        return;
      }

      setShareActionLoading(true);
      setShareStatus({ message: "共有リンクを生成しています...", error: false });

      try {
        const response = await fetch("/api/share_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId }),
        });
        const rawPayload = await readJsonBodySafe(response);
        const data = normalizeShareChatRoomPayload(rawPayload);

        if (!response.ok || !data.shareUrl) {
          throw new Error(extractApiErrorMessage(rawPayload, "共有リンクの作成に失敗しました。", response.status));
        }

        shareCacheRef.current.set(roomId, data.shareUrl);
        setShareUrl(data.shareUrl);
        setShareStatus({ message: "共有リンクを作成しました。", error: false });
      } catch (error) {
        setShareStatus({
          message: error instanceof Error ? error.message : "共有リンクの作成に失敗しました。",
          error: true,
        });
      } finally {
        setShareActionLoading(false);
      }
    },
    [currentRoomMode, setShareActionLoading],
  );

  const openShareModal = useCallback(() => {
    if (currentRoomMode === "temporary") {
      setShareStatus({ message: "未保存チャットは共有できません。", error: true });
      return;
    }
    setShareModalOpen(true);
    void createShareLink(false);
  }, [createShareLink, currentRoomMode]);

  const copyShareLink = useCallback(async () => {
    if (!shareUrl.trim()) {
      setShareStatus({ message: "先に共有リンクを生成してください。", error: true });
      return;
    }

    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus({ message: "リンクをコピーしました。", error: false });
    } catch (error) {
      setShareStatus({
        message: error instanceof Error ? error.message : "リンクのコピーに失敗しました。",
        error: true,
      });
    }
  }, [shareUrl]);

  const shareWithNativeSheet = useCallback(async () => {
    if (!shareUrl.trim()) {
      setShareStatus({ message: "先に共有リンクを生成してください。", error: true });
      return;
    }
    if (!navigator.share) {
      setShareStatus({ message: "このブラウザはネイティブ共有に対応していません。", error: true });
      return;
    }

    try {
      await navigator.share({
        title: "Chat Core 共有チャット",
        text: "このチャットルームを共有しました。",
        url: shareUrl,
      });
      setShareStatus({ message: "共有シートを開きました。", error: false });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      setShareStatus({
        message: error instanceof Error ? error.message : "共有に失敗しました。",
        error: true,
      });
    }
  }, [shareUrl]);

  const showSetupForm = useCallback(() => {
    setPageViewState("setup");
    setSidebarOpen(false);
    setLaunchingTaskName(null);
    setSetupInfo("");
    closeShareModal();
    scheduleSetupViewportFit();
  }, [closeShareModal, setLaunchingTaskName, setPageViewState]);

  const handleAccessChat = useCallback(async () => {
    const activeRoomId = currentRoomIdRef.current;
    const preferredLoadedRoom =
      (activeRoomId ? chatRooms.find((room) => room.id === activeRoomId) : null) ?? chatRooms[0] ?? null;

    if (preferredLoadedRoom) {
      switchChatRoom(preferredLoadedRoom.id, preferredLoadedRoom.mode, { forceReload: true });
      return;
    }

    setPageViewState("chat");
    setSidebarOpen(false);
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
    currentRoomIdRef,
    loadChatRooms,
    loadLocalChatHistory,
    persistCurrentRoomId,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsLoadingOlder,
    setMessages,
    setOpenRoomActionsFor,
    setPageViewState,
    setSidebarOpen,
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
      setSidebarOpen(false);
      setPageViewState("launching");

      try {
        await Promise.all([
          createNewChatRoom(roomId, roomTitle, roomMode),
          waitForDuration(CHAT_LAUNCH_MIN_TRANSITION_MS),
        ]);
        removeStoredHistory(roomId);
        setPageViewState("chat");
        setLaunchingTaskName(null);

        void loadChatRooms();
        await generateResponse(firstMessage, selectedModel, roomId);
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
      createNewChatRoom,
      generateResponse,
      isTaskOrderEditing,
      loadChatRooms,
      persistCurrentRoomId,
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
    setSidebarOpen(false);
    setPageViewState("launching");

    try {
      await Promise.all([
        createNewChatRoom(roomId, roomTitle, roomMode),
        waitForDuration(CHAT_LAUNCH_MIN_TRANSITION_MS),
      ]);
      removeStoredHistory(roomId);
      setPageViewState("chat");

      void loadChatRooms();
      await generateResponse(firstMessage, selectedModel, roomId);
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
    createNewChatRoom,
    generateResponse,
    loadChatRooms,
    persistCurrentRoomId,
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

  const toggleTaskOrderEditing = useCallback(() => {
    setIsTaskOrderEditing((previous) => {
      const next = !previous;
      if (next) {
        setTasksExpanded(true);
      } else {
        draggingTaskIndexRef.current = null;
        setDraggingTaskIndex(null);
        setTasksExpanded(false);
        void saveTaskOrder(tasks);
      }
      return next;
    });
  }, [saveTaskOrder, tasks]);

  const handleTaskDragStart = useCallback(
    (index: number) => {
      if (!isTaskOrderEditing) return;
      draggingTaskIndexRef.current = index;
      setDraggingTaskIndex(index);
    },
    [isTaskOrderEditing],
  );

  const handleTaskDragEnd = useCallback((dragIndex: number, dropTargetIndex: number) => {
    draggingTaskIndexRef.current = null;
    setDraggingTaskIndex(null);

    if (dragIndex === dropTargetIndex) return;

    setTasks((previous) => {
      if (dragIndex < 0 || dragIndex >= previous.length) return previous;
      if (dropTargetIndex < 0 || dropTargetIndex >= previous.length) return previous;
      const next = [...previous];
      const [moved] = next.splice(dragIndex, 1);
      if (!moved) return previous;
      next.splice(dropTargetIndex, 0, moved);
      return next;
    });
  }, []);

  const handleTaskDelete = useCallback(
    async (taskName: string) => {
      const confirmed = await showConfirmModal("このタスクを削除してもよろしいですか？");
      if (!confirmed) return;

      try {
        await fetchJsonOrThrow("/api/delete_task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ task: taskName }),
        });

        setTasks((previous) => {
          const next = previous.filter((task) => task.name !== taskName);
          void saveTaskOrder(next);
          return next;
        });
        invalidateTasksCache();
      } catch (error) {
        showToast(`削除に失敗しました: ${error instanceof Error ? error.message : String(error)}`, {
          variant: "error",
        });
      }
    },
    [saveTaskOrder],
  );

  const openTaskEditModal = useCallback((task: NormalizedTask) => {
    setTaskEditForm({
      old_task: task.name,
      new_task: task.name,
      prompt_template: task.prompt_template,
      response_rules: task.response_rules,
      output_skeleton: task.output_skeleton,
      input_examples: task.input_examples,
      output_examples: task.output_examples,
    });
    setTaskEditModalOpen(true);
  }, []);

  const closeTaskEditModal = useCallback(() => {
    setTaskEditModalOpen(false);
  }, []);

  const handleTaskEditSave = useCallback(async () => {
    const payload = {
      old_task: taskEditForm.old_task,
      new_task: taskEditForm.new_task.trim(),
      prompt_template: taskEditForm.prompt_template,
      response_rules: taskEditForm.response_rules,
      output_skeleton: taskEditForm.output_skeleton,
      input_examples: taskEditForm.input_examples,
      output_examples: taskEditForm.output_examples,
    };

    if (!payload.new_task) {
      showToast("タイトルを入力してください。", { variant: "error" });
      return;
    }

    try {
      await fetchJsonOrThrow("/api/edit_task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });

      setTasks((previous) =>
        previous.map((task) => {
          if (task.name !== taskEditForm.old_task) return task;
          return {
            ...task,
            name: payload.new_task,
            prompt_template: payload.prompt_template,
            response_rules: payload.response_rules,
            output_skeleton: payload.output_skeleton,
            input_examples: payload.input_examples,
            output_examples: payload.output_examples,
          };
        }),
      );
      invalidateTasksCache();
      closeTaskEditModal();
    } catch (error) {
      showToast(`更新に失敗しました: ${error instanceof Error ? error.message : String(error)}`, {
        variant: "error",
      });
    }
  }, [closeTaskEditModal, taskEditForm]);

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
    void import("../../scripts/core/csrf");
    void import("../../scripts/components/popup_menu");
    void import("../../scripts/components/chat/popup_menu");
    void import("../../scripts/components/user_icon");
  }, []);

  useEffect(() => {
    document.body.classList.add("chat-page");
    return () => {
      clearTrackedTimeouts();
      disconnectActiveGeneration();
      document.body.classList.remove("chat-page");
      document.body.classList.remove("chat-view-active");
      document.body.classList.remove("setup-view-active");
      document.body.classList.remove("sidebar-visible");
      document.body.classList.remove("new-prompt-modal-open");
      document.body.style.overflow = "";
    };
  }, [clearTrackedTimeouts, disconnectActiveGeneration]);

  useEffect(() => {
    const chatViewActive = pageViewState === "chat" || pageViewState === "launching";
    document.body.classList.toggle("chat-view-active", chatViewActive);
    document.body.classList.toggle("setup-view-active", pageViewState === "setup");

    return () => {
      document.body.classList.remove("chat-view-active");
      document.body.classList.remove("setup-view-active");
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
    if (pageViewState !== "chat" || !sidebarOpen) {
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

  useEffect(() => {
    if (!hasBlockingModalOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [hasBlockingModalOpen]);

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

    fetch("/api/current_user", { credentials: "same-origin" })
      .then((response) => response.json())
      .then((data) => {
        if (cancelled) return;
        const nextLoggedIn = Boolean(data?.logged_in);
        writeCachedAuthState(nextLoggedIn);
        setLoggedIn(nextLoggedIn);
      })
      .catch(() => {
        if (cancelled) return;
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
    if (!cachedChatRooms) return;
    setChatRooms(cachedChatRooms);

    const activeRoomId = currentRoomIdRef.current;
    if (!activeRoomId) return;

    const activeRoom = cachedChatRooms.find((room) => room.id === activeRoomId);
    if (activeRoom) {
      setCurrentRoomMode(activeRoom.mode);
    }
  }, [cachedChatRooms]);

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
      setCurrentRoomMode("normal");
    }
  }, [authResolved, loggedIn, refreshTasks]);

  useEffect(() => {
    if (tasks.length <= taskCollapseLimit) {
      setTasksExpanded(false);
    }
  }, [taskCollapseLimit, tasks.length]);

  useEffect(() => {
    try {
      const storedRoomId = localStorage.getItem(STORAGE_KEYS.currentChatRoomId);
      if (storedRoomId) {
        setCurrentRoomId(storedRoomId);
        currentRoomIdRef.current = storedRoomId;
      }
    } catch {
      // ignore localStorage failures
    }
  }, []);

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

      if (sidebarOpen && !target.closest(".sidebar") && !target.closest("#sidebar-toggle")) {
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
        setSidebarOpen(false);
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
  }, []);

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
        title: { label: "タイトル", element: titleInputRef.current },
        prompt_content: { label: "プロンプト内容", element: contentInputRef.current },
        input_examples: { label: "入力例", element: inputExampleRef.current },
        output_examples: { label: "出力例", element: outputExampleRef.current },
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
    currentRoomId,
    currentRoomMode,
    openRoomActionsFor,
    historyHasMore,
    historyNextBeforeId,
    isLoadingOlder,
    messages,
    chatInput,
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
    setSidebarOpen,
    loadOlderChatHistory,
    setChatInput,
    handleChatInputKeyDown,
    handleSendMessage,
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
