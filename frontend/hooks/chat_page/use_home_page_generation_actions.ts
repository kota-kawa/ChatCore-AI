import { useCallback, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";

import { CHAT_HISTORY_PAGE_SIZE } from "../../lib/chat_page/constants";
import {
  normalizeChatHistoryPayload,
  normalizeChatResponsePayload,
  normalizeGenerationStatusPayload,
} from "../../lib/chat_page/api_contract";
import { isNearBottom } from "../../lib/chat_page/dom";
import { isLatestChatTurnAnswered } from "../../lib/chat_page/home_page_controller_utils";
import {
  prependUiChatMessagesWithinLimit,
  rememberStreamEventId,
} from "../../lib/chat_page/message_window";
import { nextMessageId } from "../../lib/chat_page/message_ids";
import { parseStreamEventBlock } from "../../lib/chat_page/streaming";
import {
  appendStoredHistory,
  normalizeHistorySender,
  normalizeStoredSender,
  prependStoredHistory,
  readStoredHistory,
  removeStoredHistory,
  toStoredSender,
  writeStoredHistory,
  type StoredHistoryWriteResult,
} from "../../lib/chat_page/storage";
import type {
  AttachedFile,
  ChatHistoryMessagePayload,
  ChatHistoryPagination,
  ChatRoomMode,
  UiChatMessage,
} from "../../lib/chat_page/types";
import type {
  ActiveGeneration,
  GenerationGuard,
} from "../../lib/chat_page/generation_guard";
import { STORAGE_KEYS } from "../../scripts/core/constants";
import { showToast } from "../../scripts/core/toast";
import {
  extractApiErrorMessage,
  readJsonBodySafe,
} from "../../scripts/core/runtime_validation";

const GENERATION_STREAM_RECONNECT_DELAYS_MS = [300, 900];

function waitForDuration(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

// Map server-side branch metadata onto a UI message so the branch navigator
// (‹ n/m ›) can render and switch between versions of a message.
function toBranchFields(entry: ChatHistoryMessagePayload): Partial<UiChatMessage> {
  const fields: Partial<UiChatMessage> = {};
  if (typeof entry.id === "number") fields.serverId = entry.id;
  if (typeof entry.version_index === "number") fields.versionIndex = entry.version_index;
  if (typeof entry.version_count === "number") fields.versionCount = entry.version_count;
  if (Array.isArray(entry.sibling_ids) && entry.sibling_ids.length > 0) {
    fields.siblingIds = entry.sibling_ids;
  }
  return fields;
}

type UseHomePageGenerationActionsParams = {
  abortControllerRef: MutableRefObject<AbortController | null>;
  chatMessagesRef: RefObject<HTMLDivElement>;
  currentRoomIdRef: MutableRefObject<string | null>;
  generationGuardRef: MutableRefObject<GenerationGuard | null>;
  historyHasMore: boolean;
  historyNextBeforeId: number | null;
  isLoadingOlder: boolean;
  localStorageWarningShownRef: MutableRefObject<boolean>;
  messageSeqRef: MutableRefObject<number>;
  pendingAutoScrollRef: MutableRefObject<boolean>;
  prependScrollRestoreRef: MutableRefObject<{ prevScrollHeight: number; prevScrollTop: number } | null>;
  streamLastEventIdByRoomRef: MutableRefObject<Map<string, number>>;
  setCurrentRoomId: Dispatch<SetStateAction<string | null>>;
  setCurrentRoomMode: Dispatch<SetStateAction<ChatRoomMode>>;
  setHistoryHasMore: Dispatch<SetStateAction<boolean>>;
  setHistoryNextBeforeId: Dispatch<SetStateAction<number | null>>;
  setIsGenerating: Dispatch<SetStateAction<boolean>>;
  setIsLoadingOlder: Dispatch<SetStateAction<boolean>>;
  setMessages: Dispatch<SetStateAction<UiChatMessage[]>>;
};

export function useHomePageGenerationActions({
  abortControllerRef,
  chatMessagesRef,
  currentRoomIdRef,
  generationGuardRef,
  historyHasMore,
  historyNextBeforeId,
  isLoadingOlder,
  localStorageWarningShownRef,
  messageSeqRef,
  pendingAutoScrollRef,
  prependScrollRestoreRef,
  streamLastEventIdByRoomRef,
  setCurrentRoomId,
  setCurrentRoomMode,
  setHistoryHasMore,
  setHistoryNextBeforeId,
  setIsGenerating,
  setIsLoadingOlder,
  setMessages,
}: UseHomePageGenerationActionsParams) {
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

  const removeThinkingMessages = useCallback((list: UiChatMessage[]) => {
    return list.filter((message) => message.sender !== "thinking");
  }, []);

  const acquireGeneration = useCallback(
    (roomId: string) => {
      const generation = generationGuardRef.current?.acquire(roomId) ?? null;
      if (!generation) return null;

      abortControllerRef.current = generation.abortController;
      setIsGenerating(true);
      return generation;
    },
    [],
  );

  const isGenerationActive = useCallback((generation: ActiveGeneration) => {
    return generationGuardRef.current?.isActive(generation) === true;
  }, []);

  const releaseGeneration = useCallback((generation: ActiveGeneration) => {
    if (generationGuardRef.current?.release(generation) !== true) return false;
    if (abortControllerRef.current === generation.abortController) {
      abortControllerRef.current = null;
    }
    setIsGenerating(false);
    return true;
  }, []);

  const notifyLocalStorageWriteFailure = useCallback(() => {
    if (localStorageWarningShownRef.current) return;
    localStorageWarningShownRef.current = true;
    showToast(
      "ブラウザの保存容量が不足しているため、この端末に現在のチャット状態を保存できませんでした。",
      { variant: "error" },
    );
  }, []);

  const disconnectActiveGeneration = useCallback(() => {
    const generation = generationGuardRef.current?.abortActive() ?? null;
    const abortController = generation?.abortController ?? abortControllerRef.current;
    if (!abortController) return;

    if (!generation) {
      abortController.abort();
    }
    if (abortControllerRef.current === abortController) {
      abortControllerRef.current = null;
    }
    setIsGenerating(false);

    const stoppedRoomId = generation?.roomId ?? currentRoomIdRef.current;
    if (!stoppedRoomId) return;

    setMessages((previous) => {
      if (currentRoomIdRef.current !== stoppedRoomId) return previous;
      return removeThinkingMessages(previous).map((message) => {
        if (!message.streaming) return message;
        return {
          ...message,
          streaming: false,
        };
      });
    });
  }, [removeThinkingMessages]);

  const persistCurrentRoomId = useCallback((roomId: string | null, mode?: ChatRoomMode) => {
    if (currentRoomIdRef.current !== roomId) {
      disconnectActiveGeneration();
      prependScrollRestoreRef.current = null;
      setIsLoadingOlder(false);
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
      notifyLocalStorageWriteFailure();
    }
  }, [disconnectActiveGeneration, notifyLocalStorageWriteFailure]);

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

  const notifyStoredHistoryWriteIssue = useCallback((result: StoredHistoryWriteResult) => {
    if (result.stored && !result.truncated) return;
    if (localStorageWarningShownRef.current) return;

    localStorageWarningShownRef.current = true;
    if (result.stored) {
      showToast(
        "ブラウザの保存容量が不足したため、この端末に保存するチャット表示キャッシュの古い一部を削除しました。",
        { variant: "error" },
      );
      return;
    }

    showToast(
      "ブラウザの保存容量が不足しているため、この端末にチャット履歴を保存できませんでした。リロード前に必要な内容を控えてください。",
      { variant: "error" },
    );
  }, []);

  const saveUiMessagesToLocalStorage = useCallback((roomId: string, uiMessages: UiChatMessage[]) => {
    const normalized = uiMessages
      .filter((message) => message.sender === "user" || message.sender === "assistant")
      .map((message) => ({
        text: message.text,
        sender: toStoredSender(message.sender),
      }));
    notifyStoredHistoryWriteIssue(writeStoredHistory(roomId, normalized));
  }, [notifyStoredHistoryWriteIssue]);

  const loadLocalChatHistory = useCallback(
    (roomId: string) => {
      const localEntries = readStoredHistory(roomId);
      const localMessages: UiChatMessage[] = localEntries.map((entry) => ({
        id: nextMessageId("local", messageSeqRef),
        sender: normalizeStoredSender(entry.sender),
        text: entry.text,
      }));

      prependScrollRestoreRef.current = null;
      setMessages(localMessages);
      setHistoryHasMore(false);
      setHistoryNextBeforeId(null);
      setIsLoadingOlder(false);
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
    async (response: Response, generation: ActiveGeneration) => {
      const { roomId } = generation;

      const decoder = new TextDecoder();
      let streamingMessageId: string | null = null;
      let streamedText = "";

      const ensureStreamingMessage = () => {
        if (streamingMessageId) return streamingMessageId;
        streamingMessageId = nextMessageId("assistant-stream", messageSeqRef);
        const newId = streamingMessageId;

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
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

      const updateThinkingStatus = (statusText: string) => {
        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
          return previous.map((message) => {
            if (message.sender !== "thinking") return message;
            return {
              ...message,
              text: statusText,
            };
          });
        });
        scheduleAutoScrollIfNeeded();
      };

      const finalizeStreamingMessage = (finalText: string, persist = true) => {
        if (!streamingMessageId) {
          if (finalText) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
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
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return removeThinkingMessages(previous);
            });
          }
          if (persist && finalText && isGenerationActive(generation)) {
            notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: finalText, sender: "bot" }));
          }
          scheduleAutoScrollIfNeeded(true);
          return;
        }

        const streamId = streamingMessageId;
        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
          return removeThinkingMessages(previous).map((message) => {
            if (message.id !== streamId) return message;
            return {
              ...message,
              text: finalText || message.text,
              streaming: false,
            };
          });
        });

        if (persist && finalText && isGenerationActive(generation)) {
          notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: finalText, sender: "bot" }));
        }
        scheduleAutoScrollIfNeeded(true);
      };

      const persistInterruptedStream = (message: string) => {
        if (streamedText) {
          finalizeStreamingMessage(streamedText, true);
          appendAssistantErrorMessage(roomId, message);
          return;
        }
        appendAssistantErrorMessage(roomId, message);
      };

      const openReconnectStream = async () => {
        const lastEventId = streamLastEventIdByRoomRef.current.get(roomId);
        if (typeof lastEventId !== "number" || lastEventId <= 0) return null;

        try {
          const reconnectResponse = await fetch(`/api/chat_generation_stream?room_id=${encodeURIComponent(roomId)}`, {
            credentials: "same-origin",
            signal: generation.abortController.signal,
            headers: { "Last-Event-ID": String(lastEventId) },
          });
          if (!reconnectResponse.ok) return null;
          return reconnectResponse;
        } catch {
          return null;
        }
      };

      const processBlock = (block: string, streamState: { completed: boolean; streamError: string | null }) => {
        const parsed = parseStreamEventBlock(block);
        if (!parsed) return;
        if (!isGenerationActive(generation)) return;

        if (!rememberStreamEventId(streamLastEventIdByRoomRef.current, roomId, parsed.id)) return;

        if (parsed.event === "chunk") {
          const text = typeof parsed.data.text === "string" ? parsed.data.text : "";
          if (!text) return;
          const streamId = ensureStreamingMessage();
          streamedText += text;

          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
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

        if (parsed.event === "web_search_planning_started") {
          updateThinkingStatus("検索が必要か判断しています");
          return;
        }

        if (parsed.event === "web_search_started") {
          updateThinkingStatus("関連情報を取得しています");
          return;
        }

        if (parsed.event === "web_search_completed") {
          updateThinkingStatus("検索結果を読み込んでいます");
          return;
        }

        if (parsed.event === "web_search_failed") {
          const message = typeof parsed.data.message === "string" ? parsed.data.message.trim() : "";
          if (message.includes("APIキー") || message.includes("設定")) {
            updateThinkingStatus("検索設定を確認できませんでした。回答を作成しています");
          } else if (message.includes("上限")) {
            updateThinkingStatus("Web検索の上限に達しました。回答を作成しています");
          } else {
            updateThinkingStatus("Web検索に失敗しました。回答を作成しています");
          }
          return;
        }

        if (parsed.event === "response_generation_started") {
          updateThinkingStatus("回答を作成しています");
          return;
        }

        if (parsed.event === "done") {
          streamState.completed = true;
          const responseText = typeof parsed.data.response === "string" ? parsed.data.response : streamedText;
          finalizeStreamingMessage(responseText, true);
          streamLastEventIdByRoomRef.current.delete(roomId);
          return;
        }

        if (parsed.event === "aborted") {
          streamState.completed = true;
          finalizeStreamingMessage(streamedText, false);
          return;
        }

        if (parsed.event === "error") {
          streamState.streamError =
            typeof parsed.data.message === "string"
              ? parsed.data.message
              : "ストリーミング生成中にエラーが発生しました。";
        }
      };

      const readStreamResponse = async (streamResponse: Response) => {
        if (!streamResponse.body) {
          throw new Error("ストリーム応答を受信できませんでした。");
        }

        const reader = streamResponse.body.getReader();
        const streamState = {
          completed: false,
          streamError: null as string | null,
        };
        let buffer = "";

        try {
          while (true) {
            const { value, done } = await reader.read();
            if (!isGenerationActive(generation)) return "inactive" as const;
            buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

            const blocks = buffer.split(/\r?\n\r?\n/);
            buffer = blocks.pop() || "";
            blocks.forEach((block) => processBlock(block, streamState));

            if (streamState.streamError) break;
            if (done) break;
          }
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") {
            if (generation.abortController.signal.aborted || !isGenerationActive(generation)) {
              return "aborted" as const;
            }
            return "interrupted" as const;
          }
          throw error;
        } finally {
          reader.cancel().catch(() => {
            // no-op
          });
        }

        if (streamState.streamError) {
          return {
            status: "error" as const,
            message: streamState.streamError,
          };
        }

        return streamState.completed ? ("completed" as const) : ("interrupted" as const);
      };

      let activeResponse = response;
      for (let reconnectAttempt = 0; reconnectAttempt <= GENERATION_STREAM_RECONNECT_DELAYS_MS.length; reconnectAttempt += 1) {
        const result = await readStreamResponse(activeResponse);
        if (!isGenerationActive(generation)) return;

        if (result === "completed" || result === "aborted" || result === "inactive") {
          return;
        }

        if (typeof result === "object" && result.status === "error") {
          persistInterruptedStream(
            streamedText
              ? `${result.message} ここまでの応答を保存しました。`
              : result.message,
          );
          return;
        }

        const reconnectDelay = GENERATION_STREAM_RECONNECT_DELAYS_MS[reconnectAttempt];
        if (!streamedText || reconnectDelay === undefined) {
          persistInterruptedStream(
            streamedText
              ? "ストリームが途中で終了しました。ここまでの応答を保存しました。"
              : "ストリームが途中で終了しました。",
          );
          return;
        }

        await waitForDuration(reconnectDelay);
        if (!isGenerationActive(generation)) return;

        const reconnectResponse = await openReconnectStream();
        if (!reconnectResponse) {
          persistInterruptedStream("ストリームが途中で終了しました。ここまでの応答を保存しました。");
          return;
        }
        activeResponse = reconnectResponse;
      }
    },
    [
      appendAssistantErrorMessage,
      isGenerationActive,
      notifyStoredHistoryWriteIssue,
      removeThinkingMessages,
      scheduleAutoScrollIfNeeded,
    ],
  );

  const connectToGenerationStream = useCallback(
    async (roomId: string) => {
      const generation = acquireGeneration(roomId);
      if (!generation) return;

      const thinkingId = nextMessageId("thinking", messageSeqRef);
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [
          ...removeThinkingMessages(previous),
          {
            id: thinkingId,
            sender: "thinking",
            text: "AIが応答を準備しています",
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
          signal: generation.abortController.signal,
          headers,
        });

        if (!response.ok) {
          const rawPayload = await readJsonBodySafe(response);
          if (isGenerationActive(generation)) {
            appendAssistantErrorMessage(
              roomId,
              extractApiErrorMessage(rawPayload, "チャットの応答取得に失敗しました。", response.status),
            );
          }
          return;
        }

        await consumeStreamingChatResponse(response, generation);
      } catch (error) {
        if (isGenerationActive(generation) && !(error instanceof DOMException && error.name === "AbortError")) {
          appendAssistantErrorMessage(
            roomId,
            error instanceof Error ? error.message : "チャットの応答取得に失敗しました。",
          );
        }
      } finally {
        releaseGeneration(generation);
      }
    },
    [
      acquireGeneration,
      appendAssistantErrorMessage,
      consumeStreamingChatResponse,
      isGenerationActive,
      releaseGeneration,
      removeThinkingMessages,
    ],
  );

  const loadChatHistory = useCallback(
    async (roomId: string, shouldCheckGeneration = true) => {
      try {
        let loadedHistory = await fetchChatHistoryPage(roomId);
        if (currentRoomIdRef.current !== roomId) return;

        const toUiMessages = (historyMessages: typeof loadedHistory.messages): UiChatMessage[] =>
          historyMessages.map((entry) => ({
            id: nextMessageId("history", messageSeqRef),
            sender: normalizeHistorySender(entry.sender),
            text: typeof entry.message === "string" ? entry.message : "",
            ...(entry.attached_file_names?.length ? { attachedFileNames: entry.attached_file_names } : {}),
            ...toBranchFields(entry),
          }));

        const syncLoadedHistoryState = () => {
          setCurrentRoomMode(loadedHistory.roomMode);
          setHistoryHasMore(loadedHistory.pagination.hasMore);
          setHistoryNextBeforeId(loadedHistory.pagination.nextBeforeId);
        };

        const commitHistoryMessages = (nextMessages: UiChatMessage[]) => {
          prependScrollRestoreRef.current = null;
          setIsLoadingOlder(false);
          setMessages(nextMessages);
          saveUiMessagesToLocalStorage(roomId, nextMessages);
          scheduleAutoScrollIfNeeded(true);
        };

        let uiMessages = toUiMessages(loadedHistory.messages);
        syncLoadedHistoryState();

        if (!shouldCheckGeneration) {
          commitHistoryMessages(uiMessages);
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

        if (generationStatus.is_generating && isLatestChatTurnAnswered(uiMessages)) {
          try {
            loadedHistory = await fetchChatHistoryPage(roomId);
            if (currentRoomIdRef.current !== roomId) return;
            uiMessages = toUiMessages(loadedHistory.messages);
            syncLoadedHistoryState();
          } catch {
            // Keep the already-loaded history if a consistency refresh fails.
          }
        }

        if (isLatestChatTurnAnswered(uiMessages)) {
          streamLastEventIdByRoomRef.current.delete(roomId);
          commitHistoryMessages(uiMessages);
          return;
        }

        if (generationStatus.is_generating) {
          commitHistoryMessages(uiMessages);
          void connectToGenerationStream(roomId);
          return;
        }

        if (generationStatus.has_replayable_job) {
          commitHistoryMessages(uiMessages);
          void connectToGenerationStream(roomId);
          return;
        }

        commitHistoryMessages(uiMessages);
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
      if (currentRoomIdRef.current !== roomId) {
        prependScrollRestoreRef.current = null;
        return;
      }

      const uiMessages = olderMessages.map((entry) => ({
        id: nextMessageId("history-older", messageSeqRef),
        sender: normalizeHistorySender(entry.sender),
        text: typeof entry.message === "string" ? entry.message : "",
        ...(entry.attached_file_names?.length ? { attachedFileNames: entry.attached_file_names } : {}),
        ...toBranchFields(entry),
      }));

      setMessages((previous) => prependUiChatMessagesWithinLimit(uiMessages, previous));
      setHistoryHasMore(pagination.hasMore);
      setHistoryNextBeforeId(pagination.nextBeforeId);

      notifyStoredHistoryWriteIssue(
        prependStoredHistory(
          roomId,
          uiMessages
            .filter((message) => message.sender === "user" || message.sender === "assistant")
            .map((message) => ({ text: message.text, sender: toStoredSender(message.sender) })),
        ),
      );
    } catch (error) {
      console.error("追加履歴取得失敗:", error);
      prependScrollRestoreRef.current = null;
    } finally {
      setIsLoadingOlder(false);
    }
  }, [fetchChatHistoryPage, historyHasMore, historyNextBeforeId, isLoadingOlder, notifyStoredHistoryWriteIssue]);

  const mapHistoryEntriesToUi = useCallback(
    (entries: ChatHistoryMessagePayload[], idPrefix: string): UiChatMessage[] =>
      entries.map((entry) => ({
        id: nextMessageId(idPrefix, messageSeqRef),
        sender: normalizeHistorySender(entry.sender),
        text: typeof entry.message === "string" ? entry.message : "",
        ...(entry.attached_file_names?.length ? { attachedFileNames: entry.attached_file_names } : {}),
        ...toBranchFields(entry),
      })),
    [messageSeqRef],
  );

  // Reload the active branch from the server so version indicators (‹ n/m ›)
  // reflect freshly-created branches after an edit or regeneration.
  const refreshActivePath = useCallback(
    async (roomId: string) => {
      try {
        const loaded = await fetchChatHistoryPage(roomId);
        if (currentRoomIdRef.current !== roomId) return;
        const uiMessages = mapHistoryEntriesToUi(loaded.messages, "history");
        prependScrollRestoreRef.current = null;
        setHistoryHasMore(loaded.pagination.hasMore);
        setHistoryNextBeforeId(loaded.pagination.nextBeforeId);
        setMessages(uiMessages);
        saveUiMessagesToLocalStorage(roomId, uiMessages);
        scheduleAutoScrollIfNeeded();
      } catch {
        // Keep the optimistic messages if the refresh fails.
      }
    },
    [fetchChatHistoryPage, mapHistoryEntriesToUi, saveUiMessagesToLocalStorage, scheduleAutoScrollIfNeeded],
  );

  // Switch the active branch to the requested sibling version and render the
  // resulting conversation path returned by the server.
  const switchBranch = useCallback(
    async (messageId: number, roomId: string) => {
      try {
        const response = await fetch("/api/chat_switch_branch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ chat_room_id: roomId, message_id: messageId }),
        });
        const rawPayload = await readJsonBodySafe(response);
        if (!response.ok) {
          showToast(
            extractApiErrorMessage(rawPayload, "分岐の切り替えに失敗しました。", response.status),
            { variant: "error" },
          );
          return;
        }
        if (currentRoomIdRef.current !== roomId) return;
        const payload = normalizeChatHistoryPayload(rawPayload);
        const uiMessages = mapHistoryEntriesToUi(payload.messages, "branch");
        prependScrollRestoreRef.current = null;
        setHistoryHasMore(false);
        setHistoryNextBeforeId(null);
        setMessages(uiMessages);
        saveUiMessagesToLocalStorage(roomId, uiMessages);
      } catch {
        showToast("分岐の切り替えに失敗しました。", { variant: "error" });
      }
    },
    [mapHistoryEntriesToUi, saveUiMessagesToLocalStorage],
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
    async (message: string, model: string, roomId: string, attachedFiles?: AttachedFile[]) => {
      const generation = acquireGeneration(roomId);
      if (!generation) return;

      const userMessage: UiChatMessage = {
        id: nextMessageId("user", messageSeqRef),
        sender: "user",
        text: message,
        attachedFileNames: attachedFiles?.length ? attachedFiles.map((f) => f.name) : undefined,
      };
      const thinkingMessage: UiChatMessage = {
        id: nextMessageId("thinking", messageSeqRef),
        sender: "thinking",
        text: "AIが応答を準備しています",
      };

      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [...removeThinkingMessages(previous), userMessage, thinkingMessage];
      });
      notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: message, sender: "user" }));
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
            attached_files:
              attachedFiles?.map((f) => ({
                name: f.name,
                content: f.content ?? "",
                media_type: f.mediaType ?? "",
                data_base64: f.dataBase64 ?? "",
              })) ?? [],
          }),
          signal: generation.abortController.signal,
        });

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          await consumeStreamingChatResponse(response, generation);
          return;
        }

        const rawPayload = await readJsonBodySafe(response);
        const data = normalizeChatResponsePayload(rawPayload);

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
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

        if (response.ok && data.response && isGenerationActive(generation)) {
          notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: data.response, sender: "bot" }));
        }
        scheduleAutoScrollIfNeeded(true);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          if (isGenerationActive(generation)) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return removeThinkingMessages(previous);
            });
          }
          return;
        }

        const errorMessage = error instanceof Error ? error.message : String(error);
        if (isGenerationActive(generation)) {
          appendAssistantErrorMessage(roomId, errorMessage);
        }
      } finally {
        releaseGeneration(generation);
      }
    },
    [
      acquireGeneration,
      appendAssistantErrorMessage,
      consumeStreamingChatResponse,
      isGenerationActive,
      notifyStoredHistoryWriteIssue,
      refreshActivePath,
      releaseGeneration,
      removeThinkingMessages,
      scheduleAutoScrollIfNeeded,
    ],
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

  const editAndRegenerateMessage = useCallback(
    async (newMessage: string, trailingUserCount: number, model: string, roomId: string) => {
      setMessages((previous) => {
        const userIndices: number[] = [];
        previous.forEach((m, i) => {
          if (m.sender === "user") userIndices.push(i);
        });
        if (userIndices.length <= trailingUserCount) return previous;
        const targetIdx = userIndices[userIndices.length - 1 - trailingUserCount];
        return removeThinkingMessages(previous.slice(0, targetIdx));
      });

      const stored = readStoredHistory(roomId);
      const userStoredIndices: number[] = [];
      stored.forEach((e, i) => {
        if (e.sender === "user") userStoredIndices.push(i);
      });
      if (userStoredIndices.length > trailingUserCount) {
        const targetStoredIdx = userStoredIndices[userStoredIndices.length - 1 - trailingUserCount];
        notifyStoredHistoryWriteIssue(writeStoredHistory(roomId, stored.slice(0, targetStoredIdx)));
      }

      const generation = acquireGeneration(roomId);
      if (!generation) return;

      const userMsg: UiChatMessage = {
        id: nextMessageId("user", messageSeqRef),
        sender: "user",
        text: newMessage,
      };
      const thinkingMsg: UiChatMessage = {
        id: nextMessageId("thinking", messageSeqRef),
        sender: "thinking",
        text: "AIが応答を準備しています",
      };

      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [...removeThinkingMessages(previous), userMsg, thinkingMsg];
      });
      notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: newMessage, sender: "user" }));
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      scheduleAutoScrollIfNeeded(true);

      try {
        const response = await fetch("/api/chat_edit_and_regenerate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            chat_room_id: roomId,
            new_message: newMessage,
            trailing_user_count: trailingUserCount,
            model,
          }),
          signal: generation.abortController.signal,
        });

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          await consumeStreamingChatResponse(response, generation);
          void refreshActivePath(roomId);
          return;
        }

        const rawPayload = await readJsonBodySafe(response);
        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
          return [
            ...removeThinkingMessages(previous),
            {
              id: nextMessageId("assistant-error", messageSeqRef),
              sender: "assistant",
              text: `エラー: ${extractApiErrorMessage(rawPayload, "編集・再生成に失敗しました。", response.status)}`,
              error: true,
            },
          ];
        });
        scheduleAutoScrollIfNeeded(true);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          if (isGenerationActive(generation)) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return removeThinkingMessages(previous);
            });
          }
          return;
        }
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (isGenerationActive(generation)) {
          appendAssistantErrorMessage(roomId, errorMessage);
        }
      } finally {
        releaseGeneration(generation);
      }
    },
    [
      acquireGeneration,
      appendAssistantErrorMessage,
      consumeStreamingChatResponse,
      isGenerationActive,
      notifyStoredHistoryWriteIssue,
      refreshActivePath,
      releaseGeneration,
      removeThinkingMessages,
      scheduleAutoScrollIfNeeded,
    ],
  );

  const regenerateLastResponse = useCallback(
    async (model: string, roomId: string) => {
      setMessages((previous) => {
        let lastAssistantIdx = -1;
        for (let i = previous.length - 1; i >= 0; i--) {
          if (previous[i].sender === "assistant" && !previous[i].streaming) {
            lastAssistantIdx = i;
            break;
          }
        }
        if (lastAssistantIdx < 0) return previous;
        return removeThinkingMessages(previous.slice(0, lastAssistantIdx));
      });

      const stored = readStoredHistory(roomId);
      let lastBotLocalIdx = -1;
      for (let i = stored.length - 1; i >= 0; i--) {
        if (stored[i].sender === "bot") {
          lastBotLocalIdx = i;
          break;
        }
      }
      if (lastBotLocalIdx >= 0) {
        notifyStoredHistoryWriteIssue(writeStoredHistory(roomId, stored.slice(0, lastBotLocalIdx)));
      }

      const generation = acquireGeneration(roomId);
      if (!generation) return;

      const thinkingId = nextMessageId("thinking", messageSeqRef);
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [
          ...removeThinkingMessages(previous),
          {
            id: thinkingId,
            sender: "thinking",
            text: "AIが応答を準備しています",
          },
        ];
      });
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      scheduleAutoScrollIfNeeded(true);

      try {
        const response = await fetch("/api/chat_regenerate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ chat_room_id: roomId, model }),
          signal: generation.abortController.signal,
        });

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          await consumeStreamingChatResponse(response, generation);
          void refreshActivePath(roomId);
          return;
        }

        const rawPayload = await readJsonBodySafe(response);
        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
          return [
            ...removeThinkingMessages(previous),
            {
              id: nextMessageId("assistant-error", messageSeqRef),
              sender: "assistant",
              text: `エラー: ${extractApiErrorMessage(rawPayload, "再生成に失敗しました。", response.status)}`,
              error: true,
            },
          ];
        });
        scheduleAutoScrollIfNeeded(true);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          if (isGenerationActive(generation)) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return removeThinkingMessages(previous);
            });
          }
          return;
        }
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (isGenerationActive(generation)) {
          appendAssistantErrorMessage(roomId, errorMessage);
        }
      } finally {
        releaseGeneration(generation);
      }
    },
    [
      acquireGeneration,
      appendAssistantErrorMessage,
      consumeStreamingChatResponse,
      isGenerationActive,
      notifyStoredHistoryWriteIssue,
      refreshActivePath,
      releaseGeneration,
      removeThinkingMessages,
      scheduleAutoScrollIfNeeded,
    ],
  );

  return {
    scheduleAutoScrollIfNeeded,
    disconnectActiveGeneration,
    persistCurrentRoomId,
    saveUiMessagesToLocalStorage,
    loadLocalChatHistory,
    fetchChatHistoryPage,
    connectToGenerationStream,
    loadChatHistory,
    loadOlderChatHistory,
    createNewChatRoom,
    generateResponse,
    editAndRegenerateMessage,
    regenerateLastResponse,
    switchBranch,
    stopGeneration,
    removeStoredHistory,
  };
}
