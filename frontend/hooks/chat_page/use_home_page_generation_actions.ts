import { useCallback, useRef, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";

import { CHAT_HISTORY_PAGE_SIZE } from "../../lib/chat_page/constants";
import {
  normalizeChatHistoryPayload,
  normalizeChatResponsePayload,
  normalizeGenerationStatusPayload,
} from "../../lib/chat_page/api_contract";
import {
  isLatestChatTurnAnswered,
  moveChatRoomToFront,
  removeThinkingMessages as withoutThinkingMessages,
} from "../../lib/chat_page/home_page_controller_utils";
import { prependUiChatMessagesWithinLimit } from "../../lib/chat_page/message_window";
import { nextMessageId } from "../../lib/chat_page/message_ids";
import {
  consumeGenerationStream,
  type GenerationStreamHost,
} from "../../lib/chat_page/generation_stream_consumer";
import {
  isUnrecoverableStreamStatus,
  waitForGenerationStreamReconnect,
} from "../../lib/chat_page/generation_stream_reconnect";
import { getInitialThinkingState } from "../../lib/chat_page/thinking_status";
import {
  appendStoredHistory,
  clearStoredGenerationState,
  normalizeHistorySender,
  normalizeStoredSender,
  prependStoredHistory,
  readStoredGenerationState,
  readStoredHistory,
  removeLastStoredHistoryEntry,
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
import { useTranslation } from "../../contexts/locale_context";

// サーバーが「該当ルームが見つかりません」を返したことを表すエラーコード。
// Error code the server returns when the chat room no longer exists.
const CHAT_ROOM_NOT_FOUND_CODE = "chat.room_not_found";

function isChatRoomNotFoundPayload(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;
  return (payload as { code?: unknown }).code === CHAT_ROOM_NOT_FOUND_CODE;
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

// 表示中のメッセージ列とID採番。
// The rendered message list and its id sequence.
export type HomePageMessageListPort = {
  setMessages: Dispatch<SetStateAction<UiChatMessage[]>>;
  messageSeqRef: MutableRefObject<number>;
};

// 生成の占有・中断・再開位置を持つハンドル群。
// Handles owning generation ownership, aborting and the resume position.
export type HomePageGenerationStreamPort = {
  generationGuardRef: MutableRefObject<GenerationGuard | null>;
  abortControllerRef: MutableRefObject<AbortController | null>;
  streamLastEventIdByRoomRef: MutableRefObject<Map<string, number>>;
  setIsGenerating: Dispatch<SetStateAction<boolean>>;
};

// 選択中のルームとサイドバーの一覧。
// The selected chat room and the sidebar list.
export type HomePageRoomSelectionPort = {
  currentRoomIdRef: MutableRefObject<string | null>;
  currentRoomMode: ChatRoomMode;
  setCurrentRoomId: Dispatch<SetStateAction<string | null>>;
  setCurrentRoomMode: Dispatch<SetStateAction<ChatRoomMode>>;
  setChatRooms: Dispatch<SetStateAction<ChatRoom[]>>;
};

// 履歴ページングの状態。
// Chat-history pagination state.
export type HomePageHistoryPaginationPort = {
  historyHasMore: boolean;
  historyNextBeforeId: number | null;
  isLoadingOlder: boolean;
  setHistoryHasMore: Dispatch<SetStateAction<boolean>>;
  setHistoryNextBeforeId: Dispatch<SetStateAction<number | null>>;
  setIsLoadingOlder: Dispatch<SetStateAction<boolean>>;
};

// スクロール位置の予約と復元。
// Scroll-position requests and restoration.
export type HomePageScrollRestorePort = {
  chatMessagesRef: RefObject<HTMLDivElement | null>;
  pendingAutoScrollRef: MutableRefObject<boolean>;
  prependScrollRestoreRef: MutableRefObject<{ prevScrollHeight: number; prevScrollTop: number } | null>;
};

// 送信時に同送する参照設定。
// Retrieval settings sent with each turn.
export type HomePageRetrievalSettingsPort = {
  personalKnowledgeEnabled: boolean;
  sharedPromptsEnabled: boolean;
};

export type UseHomePageGenerationActionsParams = {
  messageList: HomePageMessageListPort;
  generationStream: HomePageGenerationStreamPort;
  roomSelection: HomePageRoomSelectionPort;
  historyPagination: HomePageHistoryPaginationPort;
  scrollRestore: HomePageScrollRestorePort;
  retrievalSettings: HomePageRetrievalSettingsPort;
  setChatInput: Dispatch<SetStateAction<string>>;
};

export function useHomePageGenerationActions({
  messageList,
  generationStream,
  roomSelection,
  historyPagination,
  scrollRestore,
  retrievalSettings,
  setChatInput,
}: UseHomePageGenerationActionsParams) {
  const { messageSeqRef, setMessages } = messageList;
  const {
    abortControllerRef,
    generationGuardRef,
    setIsGenerating,
    streamLastEventIdByRoomRef,
  } = generationStream;
  const {
    currentRoomIdRef,
    currentRoomMode,
    setChatRooms,
    setCurrentRoomId,
    setCurrentRoomMode,
  } = roomSelection;
  const {
    historyHasMore,
    historyNextBeforeId,
    isLoadingOlder,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsLoadingOlder,
  } = historyPagination;
  const { chatMessagesRef, pendingAutoScrollRef, prependScrollRestoreRef } = scrollRestore;
  const { personalKnowledgeEnabled, sharedPromptsEnabled } = retrievalSettings;

  // 保存容量不足の警告は1セッション1回だけ出す。この hook 以外は読まない。
  // The storage-quota warning appears once per session; no other consumer reads it.
  const localStorageWarningShownRef = useRef(false);

  const { locale } = useTranslation();
  const localeRef = useRef(locale);
  localeRef.current = locale;
  const localize = useCallback((ja: string, en: string) => localeRef.current === "en" ? en : ja, []);
  // 次の描画で最下部へスクロールする予約。呼ぶのはユーザー自身の操作（送信・編集
  // 送信・再生成の開始・ルーム切替・履歴読み込み）と、見落とすと困るエラーのときだけ。
  // 生成中の追従スクロールには使わない。回答が伸びるたびに画面を送ると、読んでいる
  // 行が下から押し上げられ、スマホでは特に読めたものではなくなる。
  // Request a scroll to the bottom on the next render. Only user-initiated moves
  // (sending, editing, starting a regeneration, switching rooms, loading
  // history) and errors that must not be missed may call this. It is never used
  // to follow generated output: scrolling every time the answer grows pushes the
  // line the reader is on off the top, which is unreadable on a phone.
  const requestScrollToBottom = useCallback(() => {
    pendingAutoScrollRef.current = true;
  }, []);

  const removeThinkingMessages = useCallback(
    (list: UiChatMessage[]) => withoutThinkingMessages(list),
    [],
  );

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
      localize("ブラウザの保存容量が不足しているため、この端末に現在のチャット状態を保存できませんでした。", "This device does not have enough browser storage to save the current chat state."),
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
      requestScrollToBottom();
    },
    [removeThinkingMessages, requestScrollToBottom],
  );

  // 回答が1文字も返らなかったターンは、楽観表示したユーザー発話ごと取り消す。
  // サーバー側でも未回答の発話は破棄されるため残しても再送のたびに自分の発話だけが
  // 積み上がり、次ターンの文脈も「未回答の発話」から始まってしまう。
  // 入力欄が空なら本文を書き戻し、そのまま送り直せるようにする。
  // Roll back the optimistically rendered user message when a turn produced no
  // answer at all. The server discards unanswered messages too, so keeping it
  // would only stack the user's own bubbles on every retry and start the next
  // turn from an unanswered message. The text goes back into an empty composer
  // so the message can simply be sent again.
  const rollbackUnansweredUserMessage = useCallback(
    (roomId: string, userMessageId: string, message: string, unsentInputText?: string) => {
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId) return previous;
        return removeThinkingMessages(previous).filter(
          (entry) => entry.id !== userMessageId,
        );
      });
      removeLastStoredHistoryEntry(roomId, { text: message, sender: "user" });
      if (!unsentInputText) return;
      setChatInput((previous) => (previous.trim() ? previous : unsentInputText));
    },
    [removeThinkingMessages, setChatInput],
  );

  const notifyStoredHistoryWriteIssue = useCallback((result: StoredHistoryWriteResult) => {
    if (result.stored && !result.truncated) return;
    if (result.stored && result.reason === "cache_limit") return;
    if (localStorageWarningShownRef.current) return;

    localStorageWarningShownRef.current = true;
    if (result.stored) {
      showToast(
        localize("ブラウザの保存容量が不足したため、この端末に保存するチャット表示キャッシュの古い一部を削除しました。", "Browser storage was low, so some older local chat cache entries were removed."),
        { variant: "error" },
      );
      return;
    }

    showToast(
      localize("ブラウザの保存容量が不足しているため、この端末にチャット履歴を保存できませんでした。リロード前に必要な内容を控えてください。", "This device does not have enough browser storage to save chat history. Copy anything important before reloading."),
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

  const markChatRoomActive = useCallback((roomId: string) => {
    setChatRooms((previous) => moveChatRoomToFront(previous, roomId));
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
      requestScrollToBottom();
    },
    [requestScrollToBottom],
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
      throw new Error(extractApiErrorMessage(rawPayload, localize("履歴取得に失敗しました。", "Could not load chat history."), response.status));
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

  // 生成ストリームを開く唯一の窓口。再開時だけ Last-Event-ID を添える。
  // The single entry point for opening a generation stream; Last-Event-ID is
  // attached only when resuming an interrupted one.
  const openGenerationStreamRequest = useCallback(
    (roomId: string, signal: AbortSignal, headers?: Record<string, string>) =>
      resilientFetch(
        `/api/chat_generation_stream?room_id=${encodeURIComponent(roomId)}`,
        {
          credentials: "same-origin",
          signal,
          headers,
        },
        { timeoutMs: 0 }
      ),
    [],
  );

  // 復元済みの進行状態から、記憶している最終イベントIDを引き上げる。
  // Raise the remembered last event id from the persisted progress state.
  const restoreStoredLastEventId = useCallback((roomId: string) => {
    const storedGeneration = readStoredGenerationState(roomId);
    if (!storedGeneration || storedGeneration.lastEventId <= 0) return;
    const rememberedLastEventId = streamLastEventIdByRoomRef.current.get(roomId) ?? 0;
    if (storedGeneration.lastEventId > rememberedLastEventId) {
      streamLastEventIdByRoomRef.current.set(roomId, storedGeneration.lastEventId);
    }
  }, []);

  // ストリーム消費ランタイムへ渡す注入口。画面更新・永続化・再接続の窓口を束ねる。
  // The ports handed to the stream runtime: screen updates, persistence and
  // reopening the stream.
  const buildGenerationStreamHost = useCallback(
    (
      generation: ActiveGeneration,
      onUnansweredFailure?: (message: string) => void,
    ): GenerationStreamHost => {
      const { roomId } = generation;

      return {
        roomId,
        abortSignal: generation.abortController.signal,
        isActive: () => isGenerationActive(generation),
        lastEventIdByRoom: streamLastEventIdByRoomRef.current,
        localize,
        messages: {
          updateActiveMessages: (updater) => {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return updater(previous);
            });
          },
          createMessageId: (prefix) => nextMessageId(prefix, messageSeqRef),
          appendErrorMessage: (message) => appendAssistantErrorMessage(roomId, message),
          applyRoomTitle: (title) => applyRoomTitleUpdate(roomId, title),
        },
        storage: {
          readGenerationState: () => readStoredGenerationState(roomId),
          updateGenerationState: (updates) => {
            updateStoredGenerationState(roomId, updates);
          },
          clearGenerationState: () => clearStoredGenerationState(roomId),
          persistAssistantAnswer: (entry) => {
            notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, entry));
          },
        },
        openStream: (lastEventId) =>
          openGenerationStreamRequest(roomId, generation.abortController.signal, {
            "Last-Event-ID": String(lastEventId),
          }),
        onUnansweredFailure,
      };
    },
    [
      appendAssistantErrorMessage,
      applyRoomTitleUpdate,
      isGenerationActive,
      notifyStoredHistoryWriteIssue,
      openGenerationStreamRequest,
    ],
  );

  // SSE の解釈・文字送り・再接続は lib/chat_page/generation_stream_consumer.ts が持つ。
  // ここは注入口を組み立てて委譲するだけ。
  // Event interpretation, reveal pacing and reconnects live in
  // lib/chat_page/generation_stream_consumer.ts; this only wires the ports.
  const consumeStreamingChatResponse = useCallback(
    (
      response: Response,
      generation: ActiveGeneration,
      options?: { onUnansweredFailure?: (message: string) => void },
    ): Promise<boolean> =>
      consumeGenerationStream(response, buildGenerationStreamHost(generation, options?.onUnansweredFailure)),
    [buildGenerationStreamHost],
  );

  const recoverInitialGenerationStream = useCallback(
    async (roomId: string, generation: ActiveGeneration): Promise<Response | null> => {
      let reconnectAttempt = 0;

      while (isGenerationActive(generation)) {
        try {
          await waitForGenerationStreamReconnect(reconnectAttempt, generation.abortController.signal);
        } catch {
          return null;
        }
        reconnectAttempt += 1;

        try {
          const response = await openGenerationStreamRequest(roomId, generation.abortController.signal);
          if (response.ok) return response;

          // A 4xx response means the original request was not accepted (or the
          // session is no longer valid); retries cannot safely recreate a POST.
          if (isUnrecoverableStreamStatus(response.status)) return null;
        } catch {
          if (generation.abortController.signal.aborted) return null;
        }
      }

      return null;
    },
    [isGenerationActive, openGenerationStreamRequest],
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
            text: localize("思考中", "AI is preparing a response"),
            generationPhase: "preparing",
          },
        ];
      });

      const headers: Record<string, string> = {};
      restoreStoredLastEventId(roomId);
      const lastEventId = streamLastEventIdByRoomRef.current.get(roomId);
      if (typeof lastEventId === "number" && lastEventId > 0) {
        headers["Last-Event-ID"] = String(lastEventId);
      }

      try {
        const response = await openGenerationStreamRequest(roomId, generation.abortController.signal, headers);

        if (!response.ok) {
          const rawPayload = await readJsonBodySafe(response);
          if (isGenerationActive(generation)) {
            appendAssistantErrorMessage(
              roomId,
              extractApiErrorMessage(rawPayload, localize("チャットの応答取得に失敗しました。", "Could not get a chat response."), response.status),
            );
          }
          return;
        }

        await consumeStreamingChatResponse(response, generation);
      } catch (error) {
        if (isGenerationActive(generation) && !(error instanceof DOMException && error.name === "AbortError")) {
          appendAssistantErrorMessage(
            roomId,
            error instanceof Error ? error.message : localize("チャットの応答取得に失敗しました。", "Could not get a chat response."),
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
      openGenerationStreamRequest,
      releaseGeneration,
      removeThinkingMessages,
      restoreStoredLastEventId,
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
          requestScrollToBottom();
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
    [connectToGenerationStream, fetchChatHistoryPage, saveUiMessagesToLocalStorage, requestScrollToBottom],
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
        // 編集・再生成の直後に走るため、ここで下端へ送ると回答の追従スクロールが
        // 戻ってしまう。分岐表示の更新だけを行い、スクロール位置には触れない。
        // This runs right after an edit or regeneration, so scrolling here would
        // bring the follow-the-answer behaviour back. Refresh the branch data
        // only and leave the scroll position where the reader put it.
      } catch {
        // Keep the optimistic messages if the refresh fails.
      }
    },
    [fetchChatHistoryPage, mapHistoryEntriesToUi, saveUiMessagesToLocalStorage],
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
            extractApiErrorMessage(rawPayload, localize("分岐の切り替えに失敗しました。", "Could not switch branches."), response.status),
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
        showToast(localize("分岐の切り替えに失敗しました。", "Could not switch branches."), { variant: "error" });
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
      throw new Error(extractApiErrorMessage(payload, localize("チャットルーム作成に失敗しました。", "Could not create a chat."), response.status));
    }
  }, []);

  // サーバー上にルームが残っていない場合に、同じIDで作り直して会話を続けられるようにする。
  // 一時チャットの期限切れ、別タブでの削除、サーバー再起動などで起こり得るが、
  // ここで復旧しないと以後の送信がすべて「該当ルームが見つかりません」で止まる。
  // Recreate the room under the same id so the conversation can continue when the
  // server no longer has it (expired temporary chat, deleted in another tab, a
  // restarted server). Without this recovery every later message would fail with
  // "the requested chat room could not be found".
  const restoreMissingChatRoom = useCallback(
    async (roomId: string, message: string, roomMode: ChatRoomMode) => {
      const title = message.trim().slice(0, 255) || localize("新規チャット", "New chat");
      try {
        await createNewChatRoom(roomId, title, roomMode);
      } catch {
        return false;
      }

      // 一覧から消えていた場合に備えて、復旧したルームをサイドバーへ戻す。
      // Put the restored room back into the sidebar in case it had disappeared.
      if (roomMode === "normal") {
        setChatRooms((previous) =>
          previous.some((room) => room.id === roomId)
            ? previous
            : [{ id: roomId, title, createdAt: new Date().toISOString(), mode: roomMode }, ...previous],
        );
      }
      return true;
    },
    [createNewChatRoom, setChatRooms],
  );

  // 復元用の進行状態を、このターンの開始位置へ初期化する。
  // Reset the persisted progress state to the start of this turn.
  const resetStoredGenerationProgress = useCallback((roomId: string, roomMode: ChatRoomMode) => {
    streamLastEventIdByRoomRef.current.set(roomId, 0);
    writeStoredGenerationState({
      roomId,
      roomMode,
      lastEventId: 0,
      streamedText: "",
      updatedAt: Date.now(),
    });
  }, []);

  // 送信したユーザー発話と「思考中」を楽観表示し、復元用の下書きを保存する。
  // Optimistically render the sent user message plus the thinking placeholder,
  // and persist the recovery draft for this turn.
  const beginOutgoingTurn = useCallback(
    (generation: ActiveGeneration, userMessage: UiChatMessage, roomMode: ChatRoomMode) => {
      const { roomId } = generation;
      const initialThinkingState = getInitialThinkingState(
        personalKnowledgeEnabled,
        sharedPromptsEnabled,
        localeRef.current,
      );
      const thinkingMessage: UiChatMessage = {
        id: nextMessageId("thinking", messageSeqRef),
        sender: "thinking",
        ...initialThinkingState,
      };

      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [...removeThinkingMessages(previous), userMessage, thinkingMessage];
      });
      notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: userMessage.text, sender: "user" }));
      resetStoredGenerationProgress(roomId, roomMode);
      requestScrollToBottom();
    },
    [
      isGenerationActive,
      notifyStoredHistoryWriteIssue,
      personalKnowledgeEnabled,
      sharedPromptsEnabled,
      removeThinkingMessages,
      requestScrollToBottom,
      resetStoredGenerationProgress,
    ],
  );

  // 回答が1件も返らなかったターンの後始末。ユーザー発話ごと取り消してから
  // エラーを1件だけ表示するので、再送しても自分の発話が積み上がらない。
  // Clean up a turn that produced no answer: roll the user's own message back
  // and show a single error, so retrying never stacks up user bubbles.
  const createUnansweredFailureHandler = useCallback(
    (generation: ActiveGeneration, userMessageId: string, message: string, unsentInputText?: string) =>
      (errorMessage: string) => {
        if (!isGenerationActive(generation)) return;
        clearStoredGenerationState(generation.roomId);
        rollbackUnansweredUserMessage(generation.roomId, userMessageId, message, unsentInputText);
        appendAssistantErrorMessage(generation.roomId, errorMessage);
      },
    [appendAssistantErrorMessage, isGenerationActive, rollbackUnansweredUserMessage],
  );

  // 中断されたターンから「思考中」だけを取り除く。エラー表示は出さない。
  // Drop only the thinking placeholder from an aborted turn; no error is shown.
  const removeThinkingAfterAbort = useCallback(
    (generation: ActiveGeneration) => {
      if (!isGenerationActive(generation)) return;
      setMessages((previous) => {
        if (currentRoomIdRef.current !== generation.roomId || !isGenerationActive(generation)) return previous;
        return removeThinkingMessages(previous);
      });
    },
    [isGenerationActive, removeThinkingMessages],
  );

  // SSE ではない JSON 応答を、確定済みの回答として1件積む。
  // Append a non-SSE JSON reply as one settled answer message.
  const appendJsonAssistantMessage = useCallback(
    (generation: ActiveGeneration, data: { response?: string | null; parts?: ChatMessagePart[] }) => {
      const { roomId } = generation;
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
    },
    [isGenerationActive, removeThinkingMessages],
  );

  const postChatMessageRequest = useCallback(
    (
      generation: ActiveGeneration,
      payload: { message: string; model: string; attachedFiles?: AttachedFile[] },
    ) =>
      resilientFetch(
        "/api/chat",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            message: payload.message,
            chat_room_id: generation.roomId,
            model: payload.model,
            use_personal_knowledge: personalKnowledgeEnabled,
            use_shared_prompts: sharedPromptsEnabled,
            attached_files:
              payload.attachedFiles?.map((f) => ({
                name: f.name,
                content: f.content ?? "",
                media_type: f.mediaType ?? "",
                data_base64: f.dataBase64 ?? "",
              })) ?? [],
          }),
          signal: generation.abortController.signal,
        },
        { timeoutMs: 0 }
      ),
    [personalKnowledgeEnabled, sharedPromptsEnabled],
  );

  // ルームがサーバー上に無いだけなら、作り直して同じ本文をもう一度送る。
  // ここで諦めると、その画面からは二度とチャットを続けられなくなる。
  // When only the room is missing, recreate it and send the same message
  // once more; giving up here would leave the chat permanently unusable.
  const resendAfterMissingChatRoom = useCallback(
    async (
      generation: ActiveGeneration,
      message: string,
      roomMode: ChatRoomMode,
      notFoundResponse: Response,
      resend: () => Promise<Response>,
    ): Promise<Response | { failureMessage: string }> => {
      const notFoundPayload = await readJsonBodySafe(notFoundResponse);
      const restored =
        isChatRoomNotFoundPayload(notFoundPayload) &&
        isGenerationActive(generation) &&
        (await restoreMissingChatRoom(generation.roomId, message, roomMode));

      if (restored) return resend();

      return {
        failureMessage: extractApiErrorMessage(
          notFoundPayload,
          localize("チャットの送信に失敗しました。", "The message could not be sent."),
          notFoundResponse.status,
        ),
      };
    },
    [isGenerationActive, restoreMissingChatRoom],
  );

  // JSON 応答の処理。回答があれば表示・保存し、無ければ未回答として扱う。
  // Handle a JSON reply: render and persist an answer, or treat the turn as
  // unanswered when there is none.
  const applyJsonChatResponse = useCallback(
    async (
      generation: ActiveGeneration,
      response: Response,
      handleUnansweredFailure: (message: string) => void,
    ): Promise<boolean> => {
      const rawPayload = await readJsonBodySafe(response);
      const data = normalizeChatResponsePayload(rawPayload);
      const answered = response.ok && Boolean(data.response || data.parts?.length);

      if (!answered) {
        handleUnansweredFailure(
          extractApiErrorMessage(
            rawPayload,
            localize("予期しないエラーが発生しました。", "An unexpected error occurred."),
            response.ok ? undefined : response.status,
          ),
        );
        return false;
      }

      appendJsonAssistantMessage(generation, data);

      if (data.response && isGenerationActive(generation)) {
        notifyStoredHistoryWriteIssue(appendStoredHistory(generation.roomId, { text: data.response, sender: "bot" }));
        applyRoomTitleUpdate(generation.roomId, data.roomTitle);
      }
      clearStoredGenerationState(generation.roomId);
      // 回答が届いても画面は動かさない。見落とすと困るエラーだけ下端へ送る。
      // An arriving answer never moves the view; only an error, which must not
      // be missed, still pulls the view to the bottom.
      return true;
    },
    [
      appendJsonAssistantMessage,
      applyRoomTitleUpdate,
      isGenerationActive,
      notifyStoredHistoryWriteIssue,
    ],
  );

  // The POST may have reached the server even when the client loses the
  // response during a Wi-Fi/mobile handoff. Do not resend it (which could
  // create a duplicate turn); attach to the generation the server already
  // started instead.
  const attachToServerSideGeneration = useCallback(
    async (
      generation: ActiveGeneration,
      handleUnansweredFailure: (message: string) => void,
      error: unknown,
    ): Promise<boolean> => {
      const recoveredResponse = await recoverInitialGenerationStream(generation.roomId, generation);
      if (recoveredResponse && isGenerationActive(generation)) {
        return consumeStreamingChatResponse(recoveredResponse, generation, {
          onUnansweredFailure: handleUnansweredFailure,
        });
      }

      handleUnansweredFailure(error instanceof Error ? error.message : String(error));
      return false;
    },
    [consumeStreamingChatResponse, isGenerationActive, recoverInitialGenerationStream],
  );

  const generateResponse = useCallback(
    async (
      message: string,
      model: string,
      roomId: string,
      attachedFiles?: AttachedFile[],
      roomMode: ChatRoomMode = currentRoomMode,
      // 送信に失敗したときに入力欄へ書き戻す本文。タスク起動のように内部整形した
      // 本文をそのまま戻すと不自然なため、呼び出し側が「ユーザーが打った文字列」を渡す。
      // Text to restore into the composer when the send fails. The caller passes
      // what the user actually typed, because restoring an internally composed
      // message (a task launch header, for example) would look wrong.
      options?: { unsentInputText?: string },
    ): Promise<boolean> => {
      const generation = acquireGeneration(roomId);
      if (!generation) return false;
      markChatRoomActive(roomId);

      const userMessage: UiChatMessage = {
        id: nextMessageId("user", messageSeqRef),
        sender: "user",
        text: message,
        attachedFileNames: attachedFiles?.length ? attachedFiles.map((f) => f.name) : undefined,
      };
      beginOutgoingTurn(generation, userMessage, roomMode);

      const handleUnansweredFailure = createUnansweredFailureHandler(
        generation,
        userMessage.id,
        message,
        options?.unsentInputText,
      );
      const postChatMessage = () => postChatMessageRequest(generation, { message, model, attachedFiles });

      try {
        let response = await postChatMessage();
        if (response.status === 404) {
          const resent = await resendAfterMissingChatRoom(generation, message, roomMode, response, postChatMessage);
          if ("failureMessage" in resent) {
            handleUnansweredFailure(resent.failureMessage);
            return false;
          }
          response = resent;
        }

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          return await consumeStreamingChatResponse(response, generation, {
            onUnansweredFailure: handleUnansweredFailure,
          });
        }

        return await applyJsonChatResponse(generation, response, handleUnansweredFailure);
      } catch (error) {
        if (generation.abortController.signal.aborted) {
          removeThinkingAfterAbort(generation);
          return false;
        }

        return await attachToServerSideGeneration(generation, handleUnansweredFailure, error);
      } finally {
        releaseGeneration(generation);
      }
    },
    [
      acquireGeneration,
      applyJsonChatResponse,
      attachToServerSideGeneration,
      beginOutgoingTurn,
      consumeStreamingChatResponse,
      createUnansweredFailureHandler,
      currentRoomMode,
      markChatRoomActive,
      postChatMessageRequest,
      refreshActivePath,
      releaseGeneration,
      removeThinkingAfterAbort,
      resendAfterMissingChatRoom,
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

  // 編集対象より後ろを、画面と表示キャッシュの両方から切り落とす。
  // Trim everything after the edit target from both the screen and the cache.
  const truncateHistoryForEdit = useCallback(
    (roomId: string, trailingUserCount: number) => {
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
    },
    [notifyStoredHistoryWriteIssue, removeThinkingMessages],
  );

  const editAndRegenerateMessage = useCallback(
    async (newMessage: string, trailingUserCount: number, model: string, roomId: string) => {
      truncateHistoryForEdit(roomId, trailingUserCount);

      const generation = acquireGeneration(roomId);
      if (!generation) return;
      markChatRoomActive(roomId);

      const userMsg: UiChatMessage = {
        id: nextMessageId("user", messageSeqRef),
        sender: "user",
        text: newMessage,
      };
      beginOutgoingTurn(generation, userMsg, currentRoomMode);

      // 編集した発話も回答が返らなければサーバー側で破棄される。画面にだけ残すと
      // 送り直すたびに自分の発話が積み上がるため、同じように取り消す。
      // An edited message is discarded server-side when no answer comes back, so
      // roll it back here too instead of stacking it on every retry.
      const handleUnansweredFailure = createUnansweredFailureHandler(generation, userMsg.id, newMessage);

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
              use_personal_knowledge: personalKnowledgeEnabled,
              use_shared_prompts: sharedPromptsEnabled,
            }),
            signal: generation.abortController.signal,
          },
          { timeoutMs: 0 }
        );

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          await consumeStreamingChatResponse(response, generation, {
            onUnansweredFailure: handleUnansweredFailure,
          });
          void refreshActivePath(roomId);
          return;
        }

        const rawPayload = await readJsonBodySafe(response);
        const data = normalizeChatResponsePayload(rawPayload);
        if (response.ok && (data.response || data.parts?.length)) {
          appendJsonAssistantMessage(generation, data);
          if (data.response) {
            notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: data.response, sender: "bot" }));
          }
          clearStoredGenerationState(roomId);
          void refreshActivePath(roomId);
          return;
        }

        handleUnansweredFailure(
          extractApiErrorMessage(
            rawPayload,
            localize("編集・再生成に失敗しました。", "Could not edit and regenerate."),
            response.ok ? undefined : response.status,
          ),
        );
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          removeThinkingAfterAbort(generation);
          return;
        }
        handleUnansweredFailure(error instanceof Error ? error.message : String(error));
      } finally {
        releaseGeneration(generation);
      }
    },
    [
      acquireGeneration,
      appendJsonAssistantMessage,
      beginOutgoingTurn,
      consumeStreamingChatResponse,
      createUnansweredFailureHandler,
      currentRoomMode,
      markChatRoomActive,
      notifyStoredHistoryWriteIssue,
      personalKnowledgeEnabled,
      sharedPromptsEnabled,
      refreshActivePath,
      releaseGeneration,
      removeThinkingAfterAbort,
      truncateHistoryForEdit,
    ],
  );

  // 直前の回答（と表示キャッシュの最後のbot発話）を取り消して再生成に備える。
  // Drop the previous answer (and the last cached bot entry) before regenerating.
  const truncateLastAnswerForRegenerate = useCallback(
    (roomId: string) => {
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
    },
    [notifyStoredHistoryWriteIssue, removeThinkingMessages],
  );

  // 再生成は新しいユーザー発話を伴わないので、「思考中」だけを積む。
  // A regeneration adds no user message, so only the thinking placeholder appears.
  const beginRegeneratedTurn = useCallback(
    (generation: ActiveGeneration) => {
      const { roomId } = generation;
      const thinkingId = nextMessageId("thinking", messageSeqRef);
      const initialThinkingState = getInitialThinkingState(
        personalKnowledgeEnabled,
        sharedPromptsEnabled,
        localeRef.current,
      );
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
        return [
          ...removeThinkingMessages(previous),
          {
            id: thinkingId,
            sender: "thinking",
            ...initialThinkingState,
          },
        ];
      });
      resetStoredGenerationProgress(roomId, currentRoomMode);
      requestScrollToBottom();
    },
    [
      currentRoomMode,
      isGenerationActive,
      personalKnowledgeEnabled,
      sharedPromptsEnabled,
      removeThinkingMessages,
      requestScrollToBottom,
      resetStoredGenerationProgress,
    ],
  );

  const regenerateLastResponse = useCallback(
    async (model: string, roomId: string) => {
      truncateLastAnswerForRegenerate(roomId);

      const generation = acquireGeneration(roomId);
      if (!generation) return;
      markChatRoomActive(roomId);
      beginRegeneratedTurn(generation);

      try {
        const response = await resilientFetch(
          "/api/chat_regenerate",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({
              chat_room_id: roomId,
              model,
              use_personal_knowledge: personalKnowledgeEnabled,
              use_shared_prompts: sharedPromptsEnabled,
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
          appendJsonAssistantMessage(generation, data);
          if (data.response) {
            notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: data.response, sender: "bot" }));
          }
          clearStoredGenerationState(roomId);
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
              text: `${localize("エラー", "Error")}: ${extractApiErrorMessage(rawPayload, localize("再生成に失敗しました。", "Could not regenerate the response."), response.status)}`,
              error: true,
            },
          ];
        });
        clearStoredGenerationState(roomId);
        requestScrollToBottom();
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          removeThinkingAfterAbort(generation);
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
      appendJsonAssistantMessage,
      beginRegeneratedTurn,
      consumeStreamingChatResponse,
      isGenerationActive,
      markChatRoomActive,
      notifyStoredHistoryWriteIssue,
      personalKnowledgeEnabled,
      sharedPromptsEnabled,
      refreshActivePath,
      releaseGeneration,
      removeThinkingAfterAbort,
      removeThinkingMessages,
      requestScrollToBottom,
      truncateLastAnswerForRegenerate,
    ],
  );

  return {
    requestScrollToBottom,
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
