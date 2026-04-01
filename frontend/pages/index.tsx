import Head from "next/head";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { ChatMainSection } from "../components/chat_page/chat_main_section";
import { ChatShareModal } from "../components/chat_page/modals/chat_share_modal";
import { NewPromptModal } from "../components/chat_page/modals/new_prompt_modal";
import { TaskDetailModal } from "../components/chat_page/modals/task_detail_modal";
import { TaskEditModal } from "../components/chat_page/modals/task_edit_modal";
import { SetupSection } from "../components/chat_page/setup_section";
import {
  CHAT_HISTORY_PAGE_SIZE,
  DEFAULT_MODEL,
  MODEL_OPTIONS,
} from "../lib/chat_page/constants";
import { isNearBottom } from "../lib/chat_page/dom";
import { nextMessageId } from "../lib/chat_page/message_ids";
import { parseStreamEventBlock } from "../lib/chat_page/streaming";
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
} from "../lib/chat_page/storage";
import { FALLBACK_TASKS, normalizeTaskList } from "../lib/chat_page/task_utils";
import type {
  ChatHistoryPayload,
  ChatRoom,
  GenerationStatusPayload,
  NormalizedTask,
  PromptAssistController,
  PromptStatus,
  TaskEditFormState,
  UiChatMessage,
} from "../lib/chat_page/types";
import { showConfirmModal } from "../scripts/core/alert_modal";
import { STORAGE_KEYS } from "../scripts/core/constants";
import {
  extractApiErrorMessage,
  fetchJsonOrThrow,
  readJsonBodySafe,
} from "../scripts/core/runtime_validation";
import { copyTextToClipboard } from "../scripts/chat/message_utils";
import { initPromptAssist } from "../scripts/components/prompt_assist";
import type { TaskItem } from "../scripts/setup/setup_types";
import {
  invalidateTasksCache,
  readCachedTasks,
  writeCachedTasks,
} from "../scripts/setup/setup_tasks_cache";
import { bindSetupViewportFit, scheduleSetupViewportFit } from "../scripts/setup/setup_viewport";

export default function HomePage() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [authResolved, setAuthResolved] = useState(false);
  const [isChatVisible, setIsChatVisible] = useState(false);
  const [setupInfo, setSetupInfo] = useState("");

  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [chatHeaderModelMenuOpen, setChatHeaderModelMenuOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState(DEFAULT_MODEL);

  const [tasks, setTasks] = useState<NormalizedTask[]>(FALLBACK_TASKS);
  const [tasksExpanded, setTasksExpanded] = useState(false);
  const [isTaskOrderEditing, setIsTaskOrderEditing] = useState(false);
  const [taskDetail, setTaskDetail] = useState<NormalizedTask | null>(null);

  const [isNewPromptModalOpen, setIsNewPromptModalOpen] = useState(false);
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [newPromptTitle, setNewPromptTitle] = useState("");
  const [newPromptContent, setNewPromptContent] = useState("");
  const [newPromptInputExample, setNewPromptInputExample] = useState("");
  const [newPromptOutputExample, setNewPromptOutputExample] = useState("");
  const [newPromptStatus, setNewPromptStatus] = useState<PromptStatus>({ message: "", variant: "info" });
  const [isPromptSubmitting, setIsPromptSubmitting] = useState(false);

  const [taskEditModalOpen, setTaskEditModalOpen] = useState(false);
  const [taskEditForm, setTaskEditForm] = useState<TaskEditFormState>({
    old_task: "",
    new_task: "",
    prompt_template: "",
    response_rules: "",
    output_skeleton: "",
    input_examples: "",
    output_examples: "",
  });

  const [chatRooms, setChatRooms] = useState<ChatRoom[]>([]);
  const [currentRoomId, setCurrentRoomId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [historyNextBeforeId, setHistoryNextBeforeId] = useState<number | null>(null);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [openRoomActionsFor, setOpenRoomActionsFor] = useState<string | null>(null);

  const [draggingTaskIndex, setDraggingTaskIndex] = useState<number | null>(null);
  const taskLaunchInProgressRef = useRef(false);

  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareStatus, setShareStatus] = useState<{ message: string; error: boolean }>({
    message: "共有するチャットルームを選択してください。",
    error: false,
  });
  const [shareUrl, setShareUrl] = useState("");
  const [shareLoading, setShareLoading] = useState(false);

  const modelSelectRef = useRef<HTMLDivElement | null>(null);
  const chatHeaderModelSelectRef = useRef<HTMLDivElement | null>(null);
  const chatMessagesRef = useRef<HTMLDivElement | null>(null);
  const newPromptAssistRootRef = useRef<HTMLDivElement | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const contentInputRef = useRef<HTMLTextAreaElement | null>(null);
  const inputExampleRef = useRef<HTMLTextAreaElement | null>(null);
  const outputExampleRef = useRef<HTMLTextAreaElement | null>(null);

  const promptAssistControllerRef = useRef<PromptAssistController | null>(null);
  const shareCacheRef = useRef<Map<string, string>>(new Map());
  const currentRoomIdRef = useRef<string | null>(null);
  const streamLastEventIdByRoomRef = useRef<Map<string, number>>(new Map());
  const abortControllerRef = useRef<AbortController | null>(null);
  const messageSeqRef = useRef(0);
  const pendingAutoScrollRef = useRef(false);
  const prependScrollRestoreRef = useRef<{ prevScrollHeight: number; prevScrollTop: number } | null>(null);

  const hasCurrentRoom = Boolean(currentRoomId);
  const showTaskToggleButton = tasks.length > 6 && !isTaskOrderEditing;
  const visibleTaskCountText = tasksExpanded || isTaskOrderEditing ? "閉じる" : "もっと見る";

  const selectedModelLabel = useMemo(() => {
    return MODEL_OPTIONS.find((option) => option.value === selectedModel)?.label ?? MODEL_OPTIONS[0]?.label ?? "";
  }, [selectedModel]);

  const selectedModelShortLabel = useMemo(() => {
    return MODEL_OPTIONS.find((option) => option.value === selectedModel)?.shortLabel ?? MODEL_OPTIONS[0]?.shortLabel ?? "";
  }, [selectedModel]);

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

  const persistCurrentRoomId = useCallback((roomId: string | null) => {
    currentRoomIdRef.current = roomId;
    setCurrentRoomId(roomId);
    try {
      if (roomId) {
        localStorage.setItem(STORAGE_KEYS.currentChatRoomId, roomId);
      } else {
        localStorage.removeItem(STORAGE_KEYS.currentChatRoomId);
      }
    } catch {
      // ignore localStorage failures
    }
  }, []);

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
    const rawPayload = (await readJsonBodySafe(response)) as ChatHistoryPayload;

    if (!response.ok || rawPayload.error) {
      throw new Error(extractApiErrorMessage(rawPayload, "履歴取得に失敗しました。", response.status));
    }

    const historyMessages = Array.isArray(rawPayload.messages) ? rawPayload.messages : [];
    const pagination = rawPayload.pagination || {};

    return {
      messages: historyMessages,
      pagination: {
        has_more: pagination.has_more === true,
        next_before_id: typeof pagination.next_before_id === "number" ? pagination.next_before_id : null,
      },
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
      if (isGenerating) return;

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
          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId) return previous;
            return removeThinkingMessages(previous);
          });
          return;
        }

        await consumeStreamingChatResponse(response, roomId);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId) return previous;
            return removeThinkingMessages(previous);
          });
        }
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
          setIsGenerating(false);
        }
      }
    },
    [consumeStreamingChatResponse, isGenerating, removeThinkingMessages],
  );

  const loadChatHistory = useCallback(
    async (roomId: string, shouldCheckGeneration = true) => {
      try {
        const { messages: historyMessages, pagination } = await fetchChatHistoryPage(roomId);
        if (currentRoomIdRef.current !== roomId) return;

        const uiMessages: UiChatMessage[] = historyMessages.map((entry) => ({
          id: nextMessageId("history", messageSeqRef),
          sender: normalizeHistorySender(entry.sender),
          text: typeof entry.message === "string" ? entry.message : "",
        }));

        setHistoryHasMore(pagination.has_more === true);
        setHistoryNextBeforeId(typeof pagination.next_before_id === "number" ? pagination.next_before_id : null);

        if (!shouldCheckGeneration) {
          setMessages(uiMessages);
          saveUiMessagesToLocalStorage(roomId, uiMessages);
          scheduleAutoScrollIfNeeded(true);
          return;
        }

        let generationStatus: GenerationStatusPayload = {};
        try {
          const statusResponse = await fetch(`/api/chat_generation_status?room_id=${encodeURIComponent(roomId)}`, {
            credentials: "same-origin",
          });
          generationStatus = (await readJsonBodySafe(statusResponse)) as GenerationStatusPayload;
        } catch {
          generationStatus = {};
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
      setHistoryHasMore(pagination.has_more === true);
      setHistoryNextBeforeId(typeof pagination.next_before_id === "number" ? pagination.next_before_id : null);

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

  const loadChatRooms = useCallback(async () => {
    try {
      const response = await fetch("/api/get_chat_rooms", { credentials: "same-origin" });
      const rawPayload = await readJsonBodySafe(response);
      const data = rawPayload && typeof rawPayload === "object" ? (rawPayload as { rooms?: unknown[]; error?: unknown }) : {};

      if (typeof data.error === "string" && data.error) {
        console.error("get_chat_rooms:", data.error);
        return;
      }

      const rooms = Array.isArray(data.rooms) ? data.rooms : [];
      const normalizedRooms: ChatRoom[] = rooms
        .map((room): ChatRoom | null => {
          if (!room || typeof room !== "object") return null;
          const payload = room as { id?: unknown; title?: unknown; created_at?: unknown };
          if (payload.id === undefined || payload.id === null) return null;
          return {
            id: String(payload.id),
            title: typeof payload.title === "string" && payload.title.trim() ? payload.title : "新規チャット",
            created_at: typeof payload.created_at === "string" ? payload.created_at : undefined,
          };
        })
        .filter((room): room is ChatRoom => room !== null);

      setChatRooms(normalizedRooms);
    } catch (error) {
      console.error("ルーム一覧取得失敗:", error);
    }
  }, []);

  const switchChatRoom = useCallback(
    (roomId: string) => {
      persistCurrentRoomId(roomId);
      setIsChatVisible(true);
      setSidebarOpen(false);
      setOpenRoomActionsFor(null);
      setShareStatus({ message: "共有リンクを準備しています...", error: false });
      setShareUrl("");
      loadLocalChatHistory(roomId);
      void loadChatHistory(roomId, true);
      void loadChatRooms();
    },
    [loadChatHistory, loadChatRooms, loadLocalChatHistory, persistCurrentRoomId],
  );

  const createNewChatRoom = useCallback(async (roomId: string, title: string) => {
    const response = await fetch("/api/new_chat_room", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ id: roomId, title }),
    });

    const payload = (await readJsonBodySafe(response)) as { error?: string };
    if (!response.ok || payload.error) {
      throw new Error(extractApiErrorMessage(payload, "チャットルーム作成に失敗しました。", response.status));
    }
  }, []);

  const generateResponse = useCallback(
    async (message: string, model: string, roomId: string) => {
      if (isGenerating) return;

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
        const data = rawPayload && typeof rawPayload === "object" ? (rawPayload as { response?: unknown; error?: unknown }) : {};

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId) return previous;
          const trimmed = removeThinkingMessages(previous);

          if (response.ok && typeof data.response === "string" && data.response) {
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

        if (response.ok && typeof data.response === "string" && data.response) {
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
    [appendAssistantErrorMessage, consumeStreamingChatResponse, isGenerating, removeThinkingMessages, scheduleAutoScrollIfNeeded],
  );

  const stopGeneration = useCallback(async () => {
    const abortController = abortControllerRef.current;
    if (abortController) {
      abortController.abort();
      abortControllerRef.current = null;
      setIsGenerating(false);
    }

    const roomId = currentRoomIdRef.current;
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
  }, []);

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
    const order = nextTasks
      .filter((task) => !task.is_default)
      .map((task) => task.name)
      .filter((name) => Boolean(name));

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
      window.alert(`並び順の保存に失敗: ${message}`);
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
        const data = rawPayload && typeof rawPayload === "object" ? (rawPayload as { share_url?: unknown }) : {};

        if (!response.ok || typeof data.share_url !== "string" || !data.share_url) {
          throw new Error(extractApiErrorMessage(rawPayload, "共有リンクの作成に失敗しました。", response.status));
        }

        shareCacheRef.current.set(roomId, data.share_url);
        setShareUrl(data.share_url);
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
    [setShareActionLoading],
  );

  const openShareModal = useCallback(() => {
    setShareModalOpen(true);
    void createShareLink(false);
  }, [createShareLink]);

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
    setIsChatVisible(false);
    setSidebarOpen(false);
    setSetupInfo("");
    closeShareModal();
    scheduleSetupViewportFit();
  }, [closeShareModal]);

  const handleAccessChat = useCallback(async () => {
    try {
      const response = await fetch("/api/get_chat_rooms", { credentials: "same-origin" });
      const payload = (await readJsonBodySafe(response)) as { rooms?: Array<{ id?: unknown; title?: unknown }> };
      const rooms = Array.isArray(payload.rooms)
        ? payload.rooms
            .map((room) => {
              if (!room || typeof room !== "object") return null;
              const item = room as { id?: unknown; title?: unknown };
              if (item.id === undefined || item.id === null) return null;
              return {
                id: String(item.id),
                title: typeof item.title === "string" ? item.title : "新規チャット",
              } as ChatRoom;
            })
            .filter((room): room is ChatRoom => room !== null)
        : [];

      if (rooms.length > 0) {
        setChatRooms(rooms);
        switchChatRoom(rooms[0].id);
        return;
      }

      setIsChatVisible(true);
      setMessages([]);
      persistCurrentRoomId(null);
      void loadChatRooms();
    } catch (error) {
      console.error("ルーム一覧取得失敗:", error);
      setIsChatVisible(true);
      setMessages([]);
      persistCurrentRoomId(null);
      void loadChatRooms();
    }
  }, [loadChatRooms, persistCurrentRoomId, switchChatRoom]);

  const handleNewChat = useCallback(() => {
    persistCurrentRoomId(null);
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

      const roomId = Date.now().toString();
      const currentSetupInfo = setupInfo.trim();
      const roomTitle = currentSetupInfo || "新規チャット";
      const firstMessage = currentSetupInfo
        ? `【タスク】${task.name}\n【状況・作業環境】${currentSetupInfo}`
        : `【タスク】${task.name}`;

      persistCurrentRoomId(roomId);

      try {
        await createNewChatRoom(roomId, roomTitle);
        setIsChatVisible(true);
        setMessages([]);
        setChatInput("");
        setOpenRoomActionsFor(null);
        setShareUrl("");
        setShareStatus({ message: "共有リンクを準備しています...", error: false });

        removeStoredHistory(roomId);

        void loadChatRooms();
        await generateResponse(firstMessage, selectedModel, roomId);
      } catch (error) {
        window.alert(`チャットルーム作成に失敗: ${error instanceof Error ? error.message : String(error)}`);
      } finally {
        taskLaunchInProgressRef.current = false;
      }
    },
    [createNewChatRoom, generateResponse, isTaskOrderEditing, loadChatRooms, persistCurrentRoomId, selectedModel, setupInfo],
  );

  const handleSendMessage = useCallback(() => {
    if (isGenerating) {
      void stopGeneration();
      return;
    }

    const roomId = currentRoomIdRef.current;
    if (!roomId) return;

    const message = chatInput.trim();
    if (!message) return;

    setChatInput("");
    void generateResponse(message, selectedModel, roomId);
  }, [chatInput, generateResponse, isGenerating, selectedModel, stopGeneration]);

  const handleChatInputKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLInputElement>) => {
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
        window.alert(`削除失敗: ${error instanceof Error ? error.message : String(error)}`);
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
        window.alert(`名前変更失敗: ${error instanceof Error ? error.message : String(error)}`);
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
        void saveTaskOrder(tasks);
      }
      return next;
    });
  }, [saveTaskOrder, tasks]);

  const handleTaskDragStart = useCallback(
    (event: React.DragEvent<HTMLDivElement>, index: number) => {
      if (!isTaskOrderEditing) return;
      setDraggingTaskIndex(index);
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
    },
    [isTaskOrderEditing],
  );

  const handleTaskDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>, hoverIndex: number) => {
      if (!isTaskOrderEditing) return;
      event.preventDefault();

      const dragIndexRaw = event.dataTransfer.getData("text/plain");
      const dragIndex = Number.parseInt(dragIndexRaw, 10);
      if (!Number.isFinite(dragIndex)) return;
      if (dragIndex === hoverIndex) return;

      setTasks((previous) => {
        if (dragIndex < 0 || dragIndex >= previous.length) return previous;
        if (hoverIndex < 0 || hoverIndex >= previous.length) return previous;

        const next = [...previous];
        const [moved] = next.splice(dragIndex, 1);
        if (!moved) return previous;
        next.splice(hoverIndex, 0, moved);

        event.dataTransfer.setData("text/plain", String(hoverIndex));
        setDraggingTaskIndex(hoverIndex);

        return next;
      });
    },
    [isTaskOrderEditing],
  );

  const handleTaskDragEnd = useCallback(() => {
    setDraggingTaskIndex(null);
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
        window.alert(`削除に失敗しました: ${error instanceof Error ? error.message : String(error)}`);
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
      window.alert("タイトルを入力してください。");
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
      window.alert(`更新に失敗しました: ${error instanceof Error ? error.message : String(error)}`);
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

        window.setTimeout(() => {
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
    ],
  );

  useEffect(() => {
    void import("../scripts/core/csrf");
    void import("../scripts/components/popup_menu");
    void import("../scripts/components/chat/popup_menu");
    void import("../scripts/components/user_icon");
  }, []);

  useEffect(() => {
    document.body.classList.add("chat-page");
    return () => {
      document.body.classList.remove("chat-page");
      document.body.classList.remove("sidebar-visible");
      document.body.classList.remove("new-prompt-modal-open");
      document.body.style.overflow = "";
    };
  }, []);

  useEffect(() => {
    if (!isChatVisible || !sidebarOpen) {
      document.body.classList.remove("sidebar-visible");
      return;
    }
    document.body.classList.add("sidebar-visible");
  }, [isChatVisible, sidebarOpen]);

  useEffect(() => {
    if (isNewPromptModalOpen) {
      document.body.classList.add("new-prompt-modal-open");
      document.body.style.overflow = "hidden";
      return;
    }

    document.body.classList.remove("new-prompt-modal-open");
    document.body.style.overflow = "";
  }, [isNewPromptModalOpen]);

  useEffect(() => {
    bindSetupViewportFit();
    scheduleSetupViewportFit();
  }, []);

  useEffect(() => {
    if (!isChatVisible) {
      scheduleSetupViewportFit();
    }
  }, [authResolved, isChatVisible, loggedIn, tasks.length, tasksExpanded]);

  useEffect(() => {
    currentRoomIdRef.current = currentRoomId;
  }, [currentRoomId]);

  useEffect(() => {
    const restore = prependScrollRestoreRef.current;
    if (!restore || !chatMessagesRef.current) return;

    const container = chatMessagesRef.current;
    const delta = container.scrollHeight - restore.prevScrollHeight;
    container.scrollTop = restore.prevScrollTop + delta;
    prependScrollRestoreRef.current = null;
  }, [messages]);

  useEffect(() => {
    if (!pendingAutoScrollRef.current) return;
    const container = chatMessagesRef.current;
    if (!container) return;
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
    document.dispatchEvent(
      new CustomEvent("authstatechange", {
        detail: { loggedIn },
      }),
    );
  }, [loggedIn]);

  useEffect(() => {
    if (!authResolved) return;
    if (!loggedIn && isTaskOrderEditing) {
      setIsTaskOrderEditing(false);
    }
    void refreshTasks(true);
    if (loggedIn) {
      void loadChatRooms();
    } else {
      setChatRooms([]);
    }
  }, [authResolved, isTaskOrderEditing, loadChatRooms, loggedIn, refreshTasks]);

  useEffect(() => {
    if (tasks.length <= 6) {
      setTasksExpanded(false);
    }
  }, [tasks.length]);

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
      const target = event.target as Element | null;
      if (!target) return;

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
    const onResize = () => {
      setSidebarOpen(false);
      scheduleSetupViewportFit();
    };

    window.addEventListener("resize", onResize);
    window.visualViewport?.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      window.visualViewport?.removeEventListener("resize", onResize);
    };
  }, []);

  useEffect(() => {
    if (!isNewPromptModalOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isPromptSubmitting) return;
      closeNewPromptModal();
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeNewPromptModal, isNewPromptModalOpen, isPromptSubmitting]);

  useEffect(() => {
    if (!shareModalOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeShareModal();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeShareModal, shareModalOpen]);

  useEffect(() => {
    const onCodeCopyClick = (event: MouseEvent) => {
      const target = event.target as Element | null;
      const button = target?.closest(".code-block-copy-btn") as HTMLButtonElement | null;
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
            window.setTimeout(() => {
              icon.classList.remove("bi-check-lg", "bi-x-lg");
              icon.classList.add("bi-clipboard");
            }, 2000);
          }
          if (textSpan) {
            textSpan.textContent = "Copied!";
            window.setTimeout(() => {
              textSpan.textContent = defaultLabel;
            }, 2000);
          }
        })
        .catch(() => {
          if (icon) {
            icon.classList.remove("bi-clipboard", "bi-check-lg");
            icon.classList.add("bi-x-lg");
            window.setTimeout(() => {
              icon.classList.remove("bi-check-lg", "bi-x-lg");
              icon.classList.add("bi-clipboard");
            }, 2000);
          }
          if (textSpan) {
            textSpan.textContent = "Failed";
            window.setTimeout(() => {
              textSpan.textContent = defaultLabel;
            }, 2000);
          }
        });
    };

    document.addEventListener("click", onCodeCopyClick);
    return () => {
      document.removeEventListener("click", onCodeCopyClick);
    };
  }, []);

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

  const shareXUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent("このチャットルームを共有しました。");
    return `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`;
  }, [shareUrl]);

  const shareLineUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    return `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`;
  }, [shareUrl]);

  const shareFacebookUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    return `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`;
  }, [shareUrl]);

  const supportsNativeShare =
    typeof navigator !== "undefined"
    && typeof (navigator as Navigator & { share?: unknown }).share === "function";

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <title>ChatCore-AI</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
      </Head>

      <div className="chat-page-shell">
        <action-menu></action-menu>

        <div
          id="auth-buttons"
          style={{
            display: loggedIn ? "none" : "flex",
            position: "fixed",
            top: 10,
            right: 10,
            zIndex: 2000,
          }}
        >
          <button id="login-btn" className="auth-btn" onClick={() => {
            window.location.href = "/login";
          }}>
            <i className="bi bi-person-circle"></i>
            <span>ログイン / 登録</span>
          </button>
        </div>

        <user-icon id="userIcon" style={{ display: loggedIn ? "" : "none" }}></user-icon>

        <SetupSection
          isChatVisible={isChatVisible}
          loggedIn={loggedIn}
          setupInfo={setupInfo}
          selectedModel={selectedModel}
          modelMenuOpen={modelMenuOpen}
          selectedModelLabel={selectedModelLabel}
          tasks={tasks}
          isTaskOrderEditing={isTaskOrderEditing}
          isNewPromptModalOpen={isNewPromptModalOpen}
          tasksExpanded={tasksExpanded}
          showTaskToggleButton={showTaskToggleButton}
          visibleTaskCountText={visibleTaskCountText}
          draggingTaskIndex={draggingTaskIndex}
          modelSelectRef={modelSelectRef}
          setSetupInfo={setSetupInfo}
          setSelectedModel={setSelectedModel}
          setModelMenuOpen={setModelMenuOpen}
          toggleTaskOrderEditing={toggleTaskOrderEditing}
          closeNewPromptModal={closeNewPromptModal}
          openNewPromptModal={openNewPromptModal}
          handleTaskDragStart={handleTaskDragStart}
          handleTaskDragOver={handleTaskDragOver}
          handleTaskDragEnd={handleTaskDragEnd}
          handleTaskCardLaunch={handleTaskCardLaunch}
          handleTaskDelete={handleTaskDelete}
          openTaskEditModal={openTaskEditModal}
          setTaskDetail={setTaskDetail}
          setTasksExpanded={setTasksExpanded}
          handleAccessChat={handleAccessChat}
        />

        <ChatMainSection
          isChatVisible={isChatVisible}
          chatHeaderModelMenuOpen={chatHeaderModelMenuOpen}
          selectedModel={selectedModel}
          selectedModelShortLabel={selectedModelShortLabel}
          hasCurrentRoom={hasCurrentRoom}
          sidebarOpen={sidebarOpen}
          chatRooms={chatRooms}
          currentRoomId={currentRoomId}
          openRoomActionsFor={openRoomActionsFor}
          historyHasMore={historyHasMore}
          historyNextBeforeId={historyNextBeforeId}
          isLoadingOlder={isLoadingOlder}
          messages={messages}
          chatInput={chatInput}
          isGenerating={isGenerating}
          chatHeaderModelSelectRef={chatHeaderModelSelectRef}
          chatMessagesRef={chatMessagesRef}
          showSetupForm={showSetupForm}
          setChatHeaderModelMenuOpen={setChatHeaderModelMenuOpen}
          setSelectedModel={setSelectedModel}
          openShareModal={openShareModal}
          handleNewChat={handleNewChat}
          switchChatRoom={switchChatRoom}
          setOpenRoomActionsFor={setOpenRoomActionsFor}
          handleRenameRoom={handleRenameRoom}
          handleDeleteRoom={handleDeleteRoom}
          setSidebarOpen={setSidebarOpen}
          loadOlderChatHistory={loadOlderChatHistory}
          setChatInput={setChatInput}
          handleChatInputKeyDown={handleChatInputKeyDown}
          handleSendMessage={handleSendMessage}
        />

        <TaskDetailModal
          taskDetail={taskDetail}
          onClose={() => {
            setTaskDetail(null);
          }}
        />

        <NewPromptModal
          isOpen={isNewPromptModalOpen}
          isPromptSubmitting={isPromptSubmitting}
          guardrailEnabled={guardrailEnabled}
          newPromptTitle={newPromptTitle}
          newPromptContent={newPromptContent}
          newPromptInputExample={newPromptInputExample}
          newPromptOutputExample={newPromptOutputExample}
          newPromptStatus={newPromptStatus}
          titleInputRef={titleInputRef}
          contentInputRef={contentInputRef}
          inputExampleRef={inputExampleRef}
          outputExampleRef={outputExampleRef}
          newPromptAssistRootRef={newPromptAssistRootRef}
          onClose={closeNewPromptModal}
          onSubmit={(event) => {
            void handlePromptSubmit(event);
          }}
          setGuardrailEnabled={setGuardrailEnabled}
          setNewPromptTitle={setNewPromptTitle}
          setNewPromptContent={setNewPromptContent}
          setNewPromptInputExample={setNewPromptInputExample}
          setNewPromptOutputExample={setNewPromptOutputExample}
        />

        <TaskEditModal
          taskEditModalOpen={taskEditModalOpen}
          taskEditForm={taskEditForm}
          closeTaskEditModal={closeTaskEditModal}
          setTaskEditForm={setTaskEditForm}
          onSave={() => {
            void handleTaskEditSave();
          }}
        />

        <ChatShareModal
          shareModalOpen={shareModalOpen}
          shareStatus={shareStatus}
          shareUrl={shareUrl}
          shareLoading={shareLoading}
          supportsNativeShare={supportsNativeShare}
          shareXUrl={shareXUrl}
          shareLineUrl={shareLineUrl}
          shareFacebookUrl={shareFacebookUrl}
          closeShareModal={closeShareModal}
          copyShareLink={() => {
            void copyShareLink();
          }}
          shareWithNativeSheet={() => {
            void shareWithNativeSheet();
          }}
        />
      </div>
    </>
  );
}
