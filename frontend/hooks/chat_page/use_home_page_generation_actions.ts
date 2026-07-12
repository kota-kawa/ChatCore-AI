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
  getStreamingGenerativeUiDisplayText,
  isGenerativeUiPending,
  updateStreamingTextPart,
} from "../../lib/chat_page/generative_ui_stream";
import {
  appendStoredHistory,
  clearStoredGenerationState,
  normalizeHistorySender,
  normalizeStoredSender,
  prependStoredHistory,
  readStoredGenerationState,
  readStoredHistory,
  removeStoredHistory,
  toStoredSender,
  updateStoredGenerationState,
  writeStoredActiveChatRoom,
  writeStoredGenerationState,
  writeStoredHistory,
  type StoredHistoryWriteResult,
} from "../../lib/chat_page/storage";
import type {
  AttachedFile,
  ChatGenerationPhase,
  ChatHistoryMessagePayload,
  ChatHistoryPagination,
  ChatMessagePart,
  ChatRoom,
  ChatRoomMode,
  UiChatMessage,
} from "../../lib/chat_page/types";
import type {
  ActiveGeneration,
  GenerationGuard,
} from "../../lib/chat_page/generation_guard";
import { showToast } from "../../scripts/core/toast";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import {
  extractApiErrorMessage,
  readJsonBodySafe,
} from "../../scripts/core/runtime_validation";
import { stopGenerationBeforeDisconnect } from "../../lib/chat_page/stop_generation";

const GENERATION_STREAM_RECONNECT_DELAYS_MS = [300, 900];

// ストリーム進行状態（復元用）を localStorage へ書き込む最短間隔。
// チャンク毎に全文を同期書き込みすると応答が伸びるほどメインスレッドを
// 塞ぐため、一定間隔にまとめる。復元データなのでこの粒度で十分。
// Minimum interval for persisting stream progress (recovery data) to
// localStorage. Writing the whole accumulated text on every chunk blocks the
// main thread more as the reply grows; recovery data tolerates this cadence.
const STORED_GENERATION_STATE_SYNC_INTERVAL_MS = 250;

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
  chatMessagesRef: RefObject<HTMLDivElement | null>;
  currentRoomIdRef: MutableRefObject<string | null>;
  currentRoomMode: ChatRoomMode;
  generationGuardRef: MutableRefObject<GenerationGuard | null>;
  historyHasMore: boolean;
  historyNextBeforeId: number | null;
  isLoadingOlder: boolean;
  localStorageWarningShownRef: MutableRefObject<boolean>;
  messageSeqRef: MutableRefObject<number>;
  pendingAutoScrollRef: MutableRefObject<boolean>;
  prependScrollRestoreRef: MutableRefObject<{ prevScrollHeight: number; prevScrollTop: number } | null>;
  streamLastEventIdByRoomRef: MutableRefObject<Map<string, number>>;
  setChatRooms: Dispatch<SetStateAction<ChatRoom[]>>;
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
    setMessages((previous) => {
      if (currentRoomIdRef.current !== generation.roomId) return previous;
      return removeThinkingMessages(previous).map((message) => {
        if (!message.streaming) return message;
        return {
          ...message,
          streaming: false,
        };
      });
    });
    return true;
  }, [removeThinkingMessages]);

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
    if (!writeStoredActiveChatRoom(roomId, mode)) {
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
        ...(message.parts?.length ? { parts: message.parts } : {}),
      }));
    notifyStoredHistoryWriteIssue(writeStoredHistory(roomId, normalized));
  }, [notifyStoredHistoryWriteIssue]);

  const applyRoomTitleUpdate = useCallback((roomId: string, title: unknown) => {
    if (typeof title !== "string") return;
    const normalizedTitle = title.trim();
    if (!normalizedTitle) return;

    setChatRooms((previous) =>
      previous.map((room) =>
        room.id === roomId
          ? {
              ...room,
              title: normalizedTitle,
            }
          : room,
      ),
    );
  }, [setChatRooms]);

  const loadLocalChatHistory = useCallback(
    (roomId: string) => {
      const localEntries = readStoredHistory(roomId);
      const localMessages: UiChatMessage[] = localEntries.map((entry) => ({
        id: nextMessageId("local", messageSeqRef),
        sender: normalizeStoredSender(entry.sender),
        text: entry.text,
        ...(entry.parts?.length ? { parts: entry.parts } : {}),
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

    const response = await resilientFetch(`/api/get_chat_history?${params.toString()}`, {
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
    async (response: Response, generation: ActiveGeneration): Promise<boolean> => {
      const { roomId } = generation;

      const decoder = new TextDecoder();
      const storedGeneration = readStoredGenerationState(roomId);
      if (storedGeneration && storedGeneration.lastEventId > 0) {
        const rememberedLastEventId = streamLastEventIdByRoomRef.current.get(roomId) ?? 0;
        if (storedGeneration.lastEventId > rememberedLastEventId) {
          streamLastEventIdByRoomRef.current.set(roomId, storedGeneration.lastEventId);
        }
      }

      let streamingMessageId: string | null = null;
      let streamedText = storedGeneration?.streamedText ?? "";
      let streamingParts: ChatMessagePart[] | undefined;

      // localStorage への進行状態書き込みをスロットルするための保留値とタイマー。
      // Pending values and timer used to throttle progress writes to localStorage.
      let storedStateSyncTimerId: number | null = null;
      let pendingStoredLastEventId = 0;
      let hasPendingStoredStreamedText = false;
      const flushStoredGenerationStateSync = () => {
        storedStateSyncTimerId = null;
        if (pendingStoredLastEventId <= 0 && !hasPendingStoredStreamedText) return;
        const updates = {
          ...(pendingStoredLastEventId > 0 ? { lastEventId: pendingStoredLastEventId } : {}),
          ...(hasPendingStoredStreamedText ? { streamedText } : {}),
        };
        pendingStoredLastEventId = 0;
        hasPendingStoredStreamedText = false;
        updateStoredGenerationState(roomId, updates);
      };
      const scheduleStoredGenerationStateSync = () => {
        if (storedStateSyncTimerId !== null) return;
        storedStateSyncTimerId = window.setTimeout(
          flushStoredGenerationStateSync,
          STORED_GENERATION_STATE_SYNC_INTERVAL_MS,
        );
      };

      // チャンク描画を 1 フレーム 1 回へ間引くための rAF ハンドル。表示は元々
      // リフレッシュレートでしか更新されないため見た目は変わらず、チャンク毎の
      // 全文 Markdown 変換・サニタイズ・DOM 差し替えの回数だけが減る。
      // rAF handle that coalesces chunk rendering to once per frame. The screen
      // only updates at the refresh rate anyway, so this changes nothing
      // visually; it only cuts the per-chunk full-text markdown/sanitize/DOM work.
      let chunkRenderRafId: number | null = null;
      const flushStreamedChunkRender = () => {
        chunkRenderRafId = null;
        const streamId = streamingMessageId;
        if (!streamId) return;
        const displayText = getStreamingGenerativeUiDisplayText(streamedText);
        const displayParts = updateStreamingTextPart(streamingParts, displayText);
        const generativeUiPending = isGenerativeUiPending(streamedText, streamingParts);

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
          return previous.map((message) => {
            if (message.id !== streamId) return message;
            return {
              ...message,
              text: displayText,
              streaming: true,
              generativeUiPending,
              ...(displayParts ? { parts: displayParts } : {}),
            };
          });
        });
        scheduleAutoScrollIfNeeded();
      };
      const scheduleStreamedChunkRender = () => {
        if (chunkRenderRafId !== null) return;
        chunkRenderRafId = window.requestAnimationFrame(flushStreamedChunkRender);
      };
      const cancelStreamedChunkRender = () => {
        if (chunkRenderRafId !== null) {
          window.cancelAnimationFrame(chunkRenderRafId);
          chunkRenderRafId = null;
        }
      };

      const ensureStreamingMessage = () => {
        if (streamingMessageId) return streamingMessageId;
        streamingMessageId = nextMessageId("assistant-stream", messageSeqRef);
        const newId = streamingMessageId;
        const displayText = getStreamingGenerativeUiDisplayText(streamedText);
        const displayParts = updateStreamingTextPart(streamingParts, displayText);
        const generativeUiPending = isGenerativeUiPending(streamedText, streamingParts);

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
          return [
            ...removeThinkingMessages(previous),
            {
              id: newId,
              sender: "assistant",
              text: displayText,
              streaming: true,
              generativeUiPending,
              ...(displayParts ? { parts: displayParts } : {}),
            },
          ];
        });
        scheduleAutoScrollIfNeeded();
        return newId;
      };

      const updateThinkingStatus = (statusText: string, generationPhase: ChatGenerationPhase = "preparing") => {
        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
          return previous.map((message) => {
            if (message.sender !== "thinking") return message;
            return {
              ...message,
              text: statusText,
              generationPhase,
            };
          });
        });
        scheduleAutoScrollIfNeeded();
      };

      const finalizeStreamingMessage = (
        finalText: string,
        persist = true,
        parts?: ChatMessagePart[],
      ) => {
        // 確定テキストを保留中の途中描画で上書きしないようにキャンセルする。
        // Cancel any pending partial render so it cannot overwrite the final text.
        cancelStreamedChunkRender();
        const finalDisplayText = finalText || getStreamingGenerativeUiDisplayText(streamedText);
        const resolvedParts = Array.isArray(parts) && parts.length > 0
          ? parts
          : updateStreamingTextPart(streamingParts, finalDisplayText);
        const hasParts = Array.isArray(resolvedParts) && resolvedParts.length > 0;
        if (!streamingMessageId) {
          if (finalDisplayText || hasParts) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return [
                ...removeThinkingMessages(previous),
                {
                  id: nextMessageId("assistant", messageSeqRef),
                  sender: "assistant",
                  text: finalDisplayText,
                  ...(hasParts ? { parts: resolvedParts } : {}),
                },
              ];
            });
          } else {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return removeThinkingMessages(previous);
            });
          }
          if (persist && finalDisplayText && isGenerationActive(generation)) {
            notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, {
              text: finalDisplayText,
              sender: "bot",
              ...(hasParts ? { parts: resolvedParts } : {}),
            }));
          }
          clearStoredGenerationState(roomId);
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
              text: finalDisplayText || message.text,
              ...(hasParts ? { parts: resolvedParts } : {}),
              streaming: false,
              generativeUiPending: false,
            };
          });
        });

        if (persist && finalDisplayText && isGenerationActive(generation)) {
          notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, {
            text: finalDisplayText,
            sender: "bot",
            ...(hasParts ? { parts: resolvedParts } : {}),
          }));
        }
        clearStoredGenerationState(roomId);
        scheduleAutoScrollIfNeeded(true);
      };

      const persistInterruptedStream = (message: string) => {
        if (streamedText) {
          finalizeStreamingMessage(getStreamingGenerativeUiDisplayText(streamedText), true, streamingParts);
          appendAssistantErrorMessage(roomId, message);
          return;
        }
        appendAssistantErrorMessage(roomId, message);
      };

      if (streamedText) {
        ensureStreamingMessage();
      }

      const openReconnectStream = async () => {
        const lastEventId = streamLastEventIdByRoomRef.current.get(roomId);
        if (typeof lastEventId !== "number" || lastEventId <= 0) return null;

        try {
          const reconnectResponse = await resilientFetch(
            `/api/chat_generation_stream?room_id=${encodeURIComponent(roomId)}`,
            {
              credentials: "same-origin",
              signal: generation.abortController.signal,
              headers: { "Last-Event-ID": String(lastEventId) },
            },
            { timeoutMs: 0 }
          );
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
        if (typeof parsed.id === "number" && parsed.id > 0) {
          pendingStoredLastEventId = parsed.id;
          scheduleStoredGenerationStateSync();
        }

        if (parsed.event === "chunk") {
          const text = typeof parsed.data.text === "string" ? parsed.data.text : "";
          if (!text) return;
          ensureStreamingMessage();
          streamedText += text;
          hasPendingStoredStreamedText = true;
          scheduleStoredGenerationStateSync();
          scheduleStreamedChunkRender();
          return;
        }

        if (parsed.event === "response_parts_updated") {
          // 直後に最新テキストで即時描画するため、保留中のチャンク描画は破棄する。
          // Drop the pending chunk render; the immediate update below already
          // carries the latest text.
          cancelStreamedChunkRender();
          const updatePayload = normalizeChatResponsePayload(parsed.data);
          const displayText = updatePayload.response ?? getStreamingGenerativeUiDisplayText(streamedText);
          if (updatePayload.parts?.length) {
            streamingParts = updateStreamingTextPart(updatePayload.parts, displayText);
          }
          const streamId = ensureStreamingMessage();
          const displayParts = updateStreamingTextPart(streamingParts, displayText);
          const generativeUiPending = isGenerativeUiPending(streamedText, streamingParts);

          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
            return previous.map((message) => {
              if (message.id !== streamId) return message;
              return {
                ...message,
                text: displayText,
                streaming: true,
                generativeUiPending,
                ...(displayParts ? { parts: displayParts } : {}),
              };
            });
          });
          scheduleAutoScrollIfNeeded();
          return;
        }

        if (parsed.event === "web_search_planning_started") {
          updateThinkingStatus("検索が必要か判断しています", "web-search");
          return;
        }

        if (parsed.event === "web_search_started") {
          updateThinkingStatus("関連情報を取得しています", "web-search");
          return;
        }

        if (parsed.event === "web_search_completed") {
          updateThinkingStatus("検索結果を読み込んでいます", "web-search");
          return;
        }

        if (parsed.event === "web_search_failed") {
          const message = typeof parsed.data.message === "string" ? parsed.data.message.trim() : "";
          if (message.includes("APIキー") || message.includes("設定")) {
            updateThinkingStatus("検索設定を確認できませんでした。回答を作成しています", "generating");
          } else if (message.includes("上限")) {
            updateThinkingStatus("Web検索の上限に達しました。回答を作成しています", "generating");
          } else {
            updateThinkingStatus("Web検索に失敗しました。回答を作成しています", "generating");
          }
          return;
        }

        if (parsed.event === "response_generation_started") {
          updateThinkingStatus("回答を作成しています", "generating");
          return;
        }

        if (parsed.event === "done") {
          streamState.completed = true;
          const donePayload = normalizeChatResponsePayload(parsed.data);
          const responseText = donePayload.response ?? streamedText;
          applyRoomTitleUpdate(roomId, parsed.data.room_title);
          finalizeStreamingMessage(responseText, true, donePayload.parts);
          streamLastEventIdByRoomRef.current.delete(roomId);
          return;
        }

        if (parsed.event === "aborted") {
          streamState.completed = true;
          // 停止時にサーバーが保存した生成途中のテキストを優先して表示する。
          // Prefer the partial text the server persisted on stop so it is not lost.
          const abortedPayload = normalizeChatResponsePayload(parsed.data);
          const finalText = abortedPayload.response ?? streamedText;
          finalizeStreamingMessage(finalText, false, abortedPayload.parts);
          clearStoredGenerationState(roomId);
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

      try {
        let activeResponse = response;
        for (let reconnectAttempt = 0; reconnectAttempt <= GENERATION_STREAM_RECONNECT_DELAYS_MS.length; reconnectAttempt += 1) {
          const result = await readStreamResponse(activeResponse);
          if (!isGenerationActive(generation)) return false;

          if (result === "completed") {
            return true;
          }

          if (result === "aborted" || result === "inactive") {
            return false;
          }

          if (typeof result === "object" && result.status === "error") {
            persistInterruptedStream(
              streamedText
                ? `${result.message} ここまでの応答を保存しました。`
                : result.message,
            );
            return false;
          }

          const reconnectDelay = GENERATION_STREAM_RECONNECT_DELAYS_MS[reconnectAttempt];
          if (!streamedText || reconnectDelay === undefined) {
            persistInterruptedStream(
              streamedText
                ? "ストリームが途中で終了しました。ここまでの応答を保存しました。"
                : "ストリームが途中で終了しました。",
            );
            return false;
          }

          await waitForDuration(reconnectDelay);
          if (!isGenerationActive(generation)) return false;

          const reconnectResponse = await openReconnectStream();
          if (!reconnectResponse) {
            persistInterruptedStream("ストリームが途中で終了しました。ここまでの応答を保存しました。");
            return false;
          }
          activeResponse = reconnectResponse;
        }
        return false;
      } finally {
        // 途中終了時も保留分を確定させる。クリア済みの場合は
        // updateStoredGenerationState が no-op になるため復活はしない。
        // On any exit, settle pending work. If the stored state was already
        // cleared, updateStoredGenerationState is a no-op, so nothing revives.
        cancelStreamedChunkRender();
        if (storedStateSyncTimerId !== null) {
          window.clearTimeout(storedStateSyncTimerId);
        }
        flushStoredGenerationStateSync();
      }
    },
    [
      appendAssistantErrorMessage,
      applyRoomTitleUpdate,
      isGenerationActive,
      notifyStoredHistoryWriteIssue,
      removeThinkingMessages,
      scheduleAutoScrollIfNeeded,
    ],
  );

  const connectToGenerationStream = useCallback(
    async (roomId: string) => {
      const generation = acquireGeneration(roomId);
      if (!generation) return false;

      const thinkingId = nextMessageId("thinking", messageSeqRef);
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [
          ...removeThinkingMessages(previous),
          {
            id: thinkingId,
            sender: "thinking",
            text: "AIが応答を準備しています",
            generationPhase: "preparing",
          },
        ];
      });

      const headers: Record<string, string> = {};
      const storedGeneration = readStoredGenerationState(roomId);
      if (storedGeneration && storedGeneration.lastEventId > 0) {
        const rememberedLastEventId = streamLastEventIdByRoomRef.current.get(roomId) ?? 0;
        if (storedGeneration.lastEventId > rememberedLastEventId) {
          streamLastEventIdByRoomRef.current.set(roomId, storedGeneration.lastEventId);
        }
      }
      const lastEventId = streamLastEventIdByRoomRef.current.get(roomId);
      if (typeof lastEventId === "number" && lastEventId > 0) {
        headers["Last-Event-ID"] = String(lastEventId);
      }

      try {
        const response = await resilientFetch(
          `/api/chat_generation_stream?room_id=${encodeURIComponent(roomId)}`,
          {
            credentials: "same-origin",
            signal: generation.abortController.signal,
            headers,
          },
          { timeoutMs: 0 }
        );

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
            ...(entry.message_parts?.length ? { parts: entry.message_parts } : {}),
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
          const statusResponse = await resilientFetch(`/api/chat_generation_status?room_id=${encodeURIComponent(roomId)}`, {
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
          clearStoredGenerationState(roomId);
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

        clearStoredGenerationState(roomId);
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
        ...(entry.message_parts?.length ? { parts: entry.message_parts } : {}),
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
        ...(entry.message_parts?.length ? { parts: entry.message_parts } : {}),
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
        const response = await resilientFetch("/api/chat_switch_branch", {
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

  const createNewChatRoom = useCallback(async (
    roomId: string,
    title: string,
    mode: ChatRoomMode,
    projectId?: number | null,
  ) => {
    const response = await resilientFetch("/api/new_chat_room", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        id: roomId,
        title,
        mode,
        // プロジェクト指定時のみ project_id を送る（通常ルームのみサーバー側で紐づけ）。
        // Send project_id only when set; the server links normal rooms to the project.
        ...(projectId != null ? { project_id: projectId } : {}),
      }),
    });

    const payload = (await readJsonBodySafe(response)) as { error?: string };
    if (!response.ok || payload.error) {
      throw new Error(extractApiErrorMessage(payload, "チャットルーム作成に失敗しました。", response.status));
    }
  }, []);

  const generateResponse = useCallback(
    async (
      message: string,
      model: string,
      roomId: string,
      attachedFiles?: AttachedFile[],
      roomMode: ChatRoomMode = currentRoomMode,
    ): Promise<boolean> => {
      const generation = acquireGeneration(roomId);
      if (!generation) return false;

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
        generationPhase: "preparing",
      };

      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [...removeThinkingMessages(previous), userMessage, thinkingMessage];
      });
      notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: message, sender: "user" }));
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      writeStoredGenerationState({
        roomId,
        roomMode,
        lastEventId: 0,
        streamedText: "",
        updatedAt: Date.now(),
      });
      scheduleAutoScrollIfNeeded(true);

      try {
        const response = await resilientFetch(
          "/api/chat",
          {
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
          },
          { timeoutMs: 0 }
        );

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          return await consumeStreamingChatResponse(response, generation);
        }

        const rawPayload = await readJsonBodySafe(response);
        const data = normalizeChatResponsePayload(rawPayload);

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
          const trimmed = removeThinkingMessages(previous);

          if (response.ok && (data.response || data.parts?.length)) {
            return [
              ...trimmed,
              {
                id: nextMessageId("assistant", messageSeqRef),
                sender: "assistant",
                text: data.response ?? "",
                ...(data.parts?.length ? { parts: data.parts } : {}),
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
          applyRoomTitleUpdate(roomId, data.roomTitle);
        }
        clearStoredGenerationState(roomId);
        scheduleAutoScrollIfNeeded(true);
        return response.ok && Boolean(data.response || data.parts?.length);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          if (isGenerationActive(generation)) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return removeThinkingMessages(previous);
            });
          }
          return false;
        }

        const errorMessage = error instanceof Error ? error.message : String(error);
        if (isGenerationActive(generation)) {
          clearStoredGenerationState(roomId);
          appendAssistantErrorMessage(roomId, errorMessage);
        }
        return false;
      } finally {
        releaseGeneration(generation);
      }
    },
    [
      acquireGeneration,
      appendAssistantErrorMessage,
      applyRoomTitleUpdate,
      consumeStreamingChatResponse,
      currentRoomMode,
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
    if (!roomId) {
      disconnectActiveGeneration();
      return;
    }

    try {
      await stopGenerationBeforeDisconnect(
        roomId,
        (targetRoomId) => resilientFetch("/api/chat_stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ chat_room_id: targetRoomId }),
        }),
        disconnectActiveGeneration,
      );
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
        generationPhase: "preparing",
      };

      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [...removeThinkingMessages(previous), userMsg, thinkingMsg];
      });
      notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: newMessage, sender: "user" }));
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      writeStoredGenerationState({
        roomId,
        roomMode: currentRoomMode,
        lastEventId: 0,
        streamedText: "",
        updatedAt: Date.now(),
      });
      scheduleAutoScrollIfNeeded(true);

      try {
        const response = await resilientFetch(
          "/api/chat_edit_and_regenerate",
          {
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
          },
          { timeoutMs: 0 }
        );

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          await consumeStreamingChatResponse(response, generation);
          void refreshActivePath(roomId);
          return;
        }

        const rawPayload = await readJsonBodySafe(response);
        const data = normalizeChatResponsePayload(rawPayload);
        if (response.ok && (data.response || data.parts?.length)) {
          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
            return [
              ...removeThinkingMessages(previous),
              {
                id: nextMessageId("assistant", messageSeqRef),
                sender: "assistant",
                text: data.response ?? "",
                ...(data.parts?.length ? { parts: data.parts } : {}),
              },
            ];
          });
          if (data.response) {
            notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: data.response, sender: "bot" }));
          }
          clearStoredGenerationState(roomId);
          scheduleAutoScrollIfNeeded(true);
          void refreshActivePath(roomId);
          return;
        }

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
        clearStoredGenerationState(roomId);
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
          clearStoredGenerationState(roomId);
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
      currentRoomMode,
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
            generationPhase: "preparing",
          },
        ];
      });
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      writeStoredGenerationState({
        roomId,
        roomMode: currentRoomMode,
        lastEventId: 0,
        streamedText: "",
        updatedAt: Date.now(),
      });
      scheduleAutoScrollIfNeeded(true);

      try {
        const response = await resilientFetch(
          "/api/chat_regenerate",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ chat_room_id: roomId, model }),
            signal: generation.abortController.signal,
          },
          { timeoutMs: 0 }
        );

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          await consumeStreamingChatResponse(response, generation);
          void refreshActivePath(roomId);
          return;
        }

        const rawPayload = await readJsonBodySafe(response);
        const data = normalizeChatResponsePayload(rawPayload);
        if (response.ok && (data.response || data.parts?.length)) {
          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
            return [
              ...removeThinkingMessages(previous),
              {
                id: nextMessageId("assistant", messageSeqRef),
                sender: "assistant",
                text: data.response ?? "",
                ...(data.parts?.length ? { parts: data.parts } : {}),
              },
            ];
          });
          if (data.response) {
            notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: data.response, sender: "bot" }));
          }
          clearStoredGenerationState(roomId);
          scheduleAutoScrollIfNeeded(true);
          void refreshActivePath(roomId);
          return;
        }

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
        clearStoredGenerationState(roomId);
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
          clearStoredGenerationState(roomId);
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
      currentRoomMode,
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
