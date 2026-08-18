import { useCallback, useRef, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";

import { CHAT_HISTORY_PAGE_SIZE } from "../../lib/chat_page/constants";
import {
  normalizeChatHistoryPayload,
  normalizeChatResponsePayload,
  normalizeGenerationStatusPayload,
} from "../../lib/chat_page/api_contract";
import { isLatestChatTurnAnswered } from "../../lib/chat_page/home_page_controller_utils";
import {
  prependUiChatMessagesWithinLimit,
  rememberStreamEventId,
} from "../../lib/chat_page/message_window";
import { nextMessageId } from "../../lib/chat_page/message_ids";
import { parseStreamEventBlock } from "../../lib/chat_page/streaming";
import {
  advanceStreamPace,
  clampToCodePointBoundary,
  createStreamPace,
} from "../../lib/chat_page/stream_smoothing";
import {
  normalizeCitationChipStreamBoundary,
  splitStreamDisplayText,
} from "../../lib/chat_page/stream_display_text";
import {
  WORD_REVEAL_DURATION_MS,
  WORD_REVEAL_MAX_LAG_MS,
  clampToRevealChunkBoundary,
  clampToWordBoundary,
} from "../../lib/chat_page/streaming_word_reveal";
import {
  getStreamingGenerativeUiDisplayText,
  isGenerativeUiPending,
  updateStreamingTextPart,
} from "../../lib/chat_page/generative_ui_stream";
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
import { useTranslation } from "../../contexts/locale_context";

// SSE は回線切替時にブラウザから明示的なエラーとして通知されないことがある。
// 最初はすぐ再接続し、以後は上限付きバックオフでサーバー側で継続中の生成へ戻る。
// An SSE connection may end without a useful browser error during a network
// handoff. Reconnect immediately once, then use capped backoff while the
// generation continues on the server.
const GENERATION_STREAM_RECONNECT_DELAYS_MS = [0, 500, 1_000, 2_000, 4_000, 8_000, 15_000];

// ストリーム進行状態（復元用）を localStorage へ書き込む最短間隔。
// チャンク毎に全文を同期書き込みすると応答が伸びるほどメインスレッドを
// 塞ぐため、一定間隔にまとめる。復元データなのでこの粒度で十分。
// Minimum interval for persisting stream progress (recovery data) to
// localStorage. Writing the whole accumulated text on every chunk blocks the
// main thread more as the reply grows; recovery data tolerates this cadence.
const STORED_GENERATION_STATE_SYNC_INTERVAL_MS = 250;

// 最後に表示した語の開始待ちとフェードが終わるまで、完成メッセージへの切り替えを
// 待つ。先に streaming=false にすると、その語の span が即座に外れて演出が消える。
// Keep the message in streaming mode until the final queued word has started
// and finished fading. Switching to streaming=false earlier removes its span
// and makes the last part of a fast response snap into view.
const STREAM_REVEAL_SETTLE_MS = WORD_REVEAL_MAX_LAG_MS + WORD_REVEAL_DURATION_MS;

// サーバーが「該当ルームが見つかりません」を返したことを表すエラーコード。
// Error code the server returns when the chat room no longer exists.
const CHAT_ROOM_NOT_FOUND_CODE = "chat.room_not_found";

function isChatRoomNotFoundPayload(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;
  return (payload as { code?: unknown }).code === CHAT_ROOM_NOT_FOUND_CODE;
}

function createAbortError(signal: AbortSignal) {
  return signal.reason instanceof Error ? signal.reason : new DOMException("Aborted", "AbortError");
}

function waitForDuration(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(createAbortError(signal));
      return;
    }

    const timerId = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      window.clearTimeout(timerId);
      reject(createAbortError(signal));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function waitUntilOnline(signal: AbortSignal) {
  if (typeof window === "undefined" || navigator.onLine !== false) {
    return Promise.resolve();
  }

  return new Promise<void>((resolve, reject) => {
    const onOnline = () => {
      cleanup();
      resolve();
    };
    const onAbort = () => {
      cleanup();
      reject(createAbortError(signal));
    };
    const cleanup = () => {
      window.removeEventListener("online", onOnline);
      signal.removeEventListener("abort", onAbort);
    };

    window.addEventListener("online", onOnline, { once: true });
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

async function waitForGenerationStreamReconnect(attempt: number, signal: AbortSignal) {
  await waitUntilOnline(signal);
  const delayIndex = Math.min(attempt, GENERATION_STREAM_RECONNECT_DELAYS_MS.length - 1);
  await waitForDuration(GENERATION_STREAM_RECONNECT_DELAYS_MS[delayIndex], signal);
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
  personalKnowledgeEnabled: boolean;
  sharedPromptsEnabled: boolean;
  localStorageWarningShownRef: MutableRefObject<boolean>;
  messageSeqRef: MutableRefObject<number>;
  pendingAutoScrollRef: MutableRefObject<boolean>;
  prependScrollRestoreRef: MutableRefObject<{ prevScrollHeight: number; prevScrollTop: number } | null>;
  streamLastEventIdByRoomRef: MutableRefObject<Map<string, number>>;
  setChatInput: Dispatch<SetStateAction<string>>;
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
  personalKnowledgeEnabled,
  sharedPromptsEnabled,
  localStorageWarningShownRef,
  messageSeqRef,
  pendingAutoScrollRef,
  prependScrollRestoreRef,
  streamLastEventIdByRoomRef,
  setChatInput,
  setChatRooms,
  setCurrentRoomId,
  setCurrentRoomMode,
  setHistoryHasMore,
  setHistoryNextBeforeId,
  setIsGenerating,
  setIsLoadingOlder,
  setMessages,
}: UseHomePageGenerationActionsParams) {
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

  const consumeStreamingChatResponse = useCallback(
    async (
      response: Response,
      generation: ActiveGeneration,
      options?: { onUnansweredFailure?: (message: string) => void },
    ): Promise<boolean> => {
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
      type PendingFinalization = {
        finalText: string;
        persist: boolean;
        parts?: ChatMessagePart[];
      };
      let pendingFinalization: PendingFinalization | null = null;
      let revealCompletionPromise: Promise<void> | null = null;
      let resolveRevealCompletion: (() => void) | null = null;
      let finalRevealTimerId: number | null = null;

      // 等速ペーシングの状態。復元テキストはリプレイせず即時表示する。
      // Constant-pace state. Restored text shows instantly instead of being
      // replayed.
      const initialDisplayText = splitStreamDisplayText(
        getStreamingGenerativeUiDisplayText(streamedText),
      );
      const streamPace = createStreamPace(initialDisplayText.pacedText.length, performance.now());
      let hasSeparatedInstantPrefix = Boolean(initialDisplayText.instantPrefix);

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

      // チャンク描画を 1 フレーム 1 回へ間引くための rAF ハンドル。あわせて
      // 表示文字数を上限付きの等速ペースで進め、チャンクが塊のまま現れず文字が
      // 流れるように見せる。排出しきるまでフレーム毎に自身を再スケジュールする。
      // rAF handle that coalesces chunk rendering to once per frame. It also
      // advances the visible length at a capped, steady pace so chunks read as
      // flowing text instead of blocks, and reschedules until the backlog drains.
      let chunkRenderRafId: number | null = null;
      const finishPendingFinalization = () => {
        const pending = pendingFinalization;
        if (!pending) return;
        pendingFinalization = null;
        finalizeStreamingMessage(pending.finalText, pending.persist, pending.parts);
        resolveRevealCompletion?.();
        resolveRevealCompletion = null;
      };
      const flushStreamedChunkRender = () => {
        chunkRenderRafId = null;
        const streamId = streamingMessageId;
        if (!streamId) return;
        const fullDisplayText = getStreamingGenerativeUiDisplayText(streamedText);
        const separatedDisplayText = splitStreamDisplayText(fullDisplayText);
        const frameNow = performance.now();
        if (!hasSeparatedInstantPrefix && separatedDisplayText.instantPrefix) {
          // 不完全だった検索トレースが閉じた瞬間、そこまでHTMLへ費やしていた進捗を
          // 本文へ持ち越さない。本文は先頭から通常のテンポで表示する。
          // When an incomplete trace becomes complete, do not carry progress
          // spent on its raw HTML into the answer body. Pace the body from zero.
          streamPace.length = 0;
          streamPace.rate = 0;
          streamPace.lastTime = frameNow;
          hasSeparatedInstantPrefix = true;
        }
        const smoothedLength = clampToCodePointBoundary(
          separatedDisplayText.pacedText,
          advanceStreamPace(streamPace, separatedDisplayText.pacedText.length, frameNow),
        );
        // 表示はチャンク境界まで巻き戻し、さらに語境界へ合わせる。文字単位で
        // 伸ばすと生成中の行が毎フレーム折り返し直しになり、読んでいる文字が
        // 動いてしまう（スマホで顕著）。かたまり単位で伸ばせば折り返しの変化が
        // まばらになり、フェードインも1かたまりずつはっきり見える。
        // Pull the visible length back to a chunk boundary, then to a word
        // boundary. Growing character by character re-wraps the streaming line
        // every frame and shifts the characters being read (worst on phones);
        // growing in chunks makes re-wraps rare and each fade-in legible.
        let displayLength = clampToCodePointBoundary(
          separatedDisplayText.pacedText,
          clampToWordBoundary(
            separatedDisplayText.pacedText,
            clampToRevealChunkBoundary(separatedDisplayText.pacedText, smoothedLength),
          ),
        );
        displayLength = normalizeCitationChipStreamBoundary(
          separatedDisplayText.pacedText,
          displayLength,
        );
        // チップ内部のHTML文字数をペーシング待ちにしない。完成済みチップを一度に
        // 表示したあとは、その直後の本文から通常速度で再開する。
        // Skip markup bytes after atomically revealing a complete chip, then
        // resume normal pacing with the text immediately after it.
        if (displayLength > streamPace.length) streamPace.length = displayLength;
        const displayText = [
          separatedDisplayText.instantPrefix,
          separatedDisplayText.pacedText.slice(0, displayLength),
        ].join("");
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
        if (smoothedLength < separatedDisplayText.pacedText.length) {
          scheduleStreamedChunkRender();
          return;
        }
        if (pendingFinalization && finalRevealTimerId === null) {
          // 最終文字を streaming=true のDOMへ一度描画した後、そのCSSアニメーションが
          // 完了する時間を確保してから完成状態へ切り替える。
          // Render the final characters into the streaming DOM once, then give
          // their CSS animation time to finish before switching to the clean
          // completed markup.
          finalRevealTimerId = window.setTimeout(() => {
            finalRevealTimerId = null;
            finishPendingFinalization();
          }, STREAM_REVEAL_SETTLE_MS);
        }
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

      const queueStreamingMessageFinalization = (
        finalText: string,
        persist = true,
        parts?: ChatMessagePart[],
      ) => {
        pendingFinalization = { finalText, persist, parts };
        if (!revealCompletionPromise) {
          revealCompletionPromise = new Promise<void>((resolve) => {
            resolveRevealCompletion = resolve;
          });
        }
        scheduleStreamedChunkRender();
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
      };

      const persistInterruptedStream = (message: string) => {
        if (streamedText.trim()) {
          finalizeStreamingMessage(getStreamingGenerativeUiDisplayText(streamedText), true, streamingParts);
          appendAssistantErrorMessage(roomId, message);
          return;
        }
        // 1文字も届いていない = このターンには回答がない。呼び出し側が
        // ユーザー発話の取り消しまで含めて後始末できるよう委譲する。
        // Nothing arrived at all, so this turn has no answer. Let the caller
        // clean up, including rolling back the user's own message.
        const handleUnansweredFailure = options?.onUnansweredFailure;
        if (handleUnansweredFailure) {
          handleUnansweredFailure(message);
          return;
        }
        appendAssistantErrorMessage(roomId, message);
      };

      if (streamedText) {
        ensureStreamingMessage();
      }

      const openReconnectStream = async (): Promise<Response | "unavailable" | null> => {
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
          if (!reconnectResponse.ok) {
            if (reconnectResponse.status >= 400 && reconnectResponse.status < 500 && reconnectResponse.status !== 408 && reconnectResponse.status !== 429) {
              return "unavailable";
            }
            return null;
          }
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
          // パーツ更新はテキストの書き換えを伴うため、ペーシングせず全文を出す。
          // Parts updates rewrite the text, so show it in full without pacing.
          const separatedDisplayText = splitStreamDisplayText(displayText);
          streamPace.length = separatedDisplayText.pacedText.length;
          hasSeparatedInstantPrefix ||= Boolean(separatedDisplayText.instantPrefix);
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
          return;
        }

        if (parsed.event === "shared_prompt_search_started") {
          updateThinkingStatus(
            localize("共有プロンプトを検索しています", "Searching shared prompts"),
            "web-search",
          );
          return;
        }

        if (parsed.event === "shared_prompt_search_completed") {
          // 事前検索済みのクエリは再検索していないので、0件として扱わない
          // An already prefetched query was not searched again, so it must not read as zero hits
          if (parsed.data.status === "already_searched") {
            updateThinkingStatus(
              localize("取得済みの共有プロンプトを読み込んでいます", "Reading the shared prompts already retrieved"),
              "web-search",
            );
            return;
          }
          const promptCount = typeof parsed.data.prompt_count === "number" ? parsed.data.prompt_count : 0;
          updateThinkingStatus(
            promptCount > 0
              ? localize("見つかった共有プロンプトを読み込んでいます", "Reading the shared prompts that matched")
              : localize("該当する共有プロンプトはありませんでした。回答を作成しています", "No shared prompt matched. Preparing an answer"),
            promptCount > 0 ? "web-search" : "generating",
          );
          return;
        }

        if (parsed.event === "shared_prompt_search_failed") {
          updateThinkingStatus(
            localize("共有プロンプトの検索に失敗しました。回答を作成しています", "Shared prompt search failed. Preparing an answer"),
            "generating",
          );
          return;
        }

        if (parsed.event === "personal_knowledge_search_started") {
          updateThinkingStatus(
            localize("メモとマイコンテキストを検索しています", "Searching your memos and My Context"),
            "web-search",
          );
          return;
        }

        if (parsed.event === "personal_knowledge_search_completed") {
          // 事前検索済みのクエリは再検索していないので、0件として扱わない
          // An already prefetched query was not searched again, so it must not read as zero hits
          if (parsed.data.status === "already_searched") {
            updateThinkingStatus(
              localize("取得済みのメモを読み込んでいます", "Reading the notes already retrieved"),
              "web-search",
            );
            return;
          }
          const memoCount = typeof parsed.data.memo_count === "number" ? parsed.data.memo_count : 0;
          const factCount =
            typeof parsed.data.context_fact_count === "number" ? parsed.data.context_fact_count : 0;
          updateThinkingStatus(
            memoCount + factCount > 0
              ? localize("見つかったメモを読み込んでいます", "Reading the notes that matched")
              : localize("該当するメモはありませんでした。回答を作成しています", "No notes matched. Preparing an answer"),
            memoCount + factCount > 0 ? "web-search" : "generating",
          );
          return;
        }

        if (parsed.event === "personal_knowledge_search_failed") {
          updateThinkingStatus(
            localize("メモの検索に失敗しました。回答を作成しています", "Note search failed. Preparing an answer"),
            "generating",
          );
          return;
        }

        if (parsed.event === "web_search_planning_started") {
          updateThinkingStatus(localize("検索が必要か判断しています", "Checking whether web search is needed"), "web-search");
          return;
        }

        if (parsed.event === "web_search_started") {
          updateThinkingStatus(localize("Web検索中", "Finding relevant information"), "web-search");
          return;
        }

        if (parsed.event === "web_search_completed") {
          updateThinkingStatus(localize("検索結果を読み込んでいます", "Reading search results"), "web-search");
          return;
        }

        if (parsed.event === "web_search_failed") {
          const message = typeof parsed.data.message === "string" ? parsed.data.message.trim() : "";
          if (message.includes("APIキー") || message.includes("設定")) {
            updateThinkingStatus(localize("検索設定を確認できませんでした。回答を作成しています", "Search settings were unavailable. Preparing an answer"), "generating");
          } else if (message.includes("上限")) {
            updateThinkingStatus(localize("Web検索の上限に達しました。回答を作成しています", "The web search limit was reached. Preparing an answer"), "generating");
          } else {
            updateThinkingStatus(localize("Web検索に失敗しました。回答を作成しています", "Web search failed. Preparing an answer"), "generating");
          }
          return;
        }

        if (parsed.event === "response_generation_started") {
          updateThinkingStatus(localize("回答を作成しています", "Preparing an answer"), "generating");
          return;
        }

        if (parsed.event === "done") {
          streamState.completed = true;
          const donePayload = normalizeChatResponsePayload(parsed.data);
          const responseText = donePayload.response ?? streamedText;
          applyRoomTitleUpdate(roomId, parsed.data.room_title);
          if (!responseText.trim() && !donePayload.parts?.length) {
            // 空の完了は「回答なし」。空の吹き出しを残さずエラーとして扱う。
            // An empty completion means no answer: treat it as an error instead
            // of leaving a blank bubble behind.
            streamState.completed = false;
            streamState.streamError = localize(
              "AIからの回答が空でした。もう一度お試しください。",
              "The AI returned an empty answer. Please try again.",
            );
            streamLastEventIdByRoomRef.current.delete(roomId);
            clearStoredGenerationState(roomId);
            return;
          }
          // 最終応答を表示キューへ渡し、未表示分と最後のフェードが完了してから
          // streaming=false にする。高速応答でも末尾が一括表示されなくなる。
          // Feed the final response through the display queue and only mark it
          // complete after the remaining text and fade have drained.
          ensureStreamingMessage();
          streamedText = responseText;
          queueStreamingMessageFinalization(responseText, true, donePayload.parts);
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
              : localize("ストリーミング生成中にエラーが発生しました。", "An error occurred while streaming the response.");
        }
      };

      const readStreamResponse = async (streamResponse: Response) => {
        if (!streamResponse.body) {
          throw new Error(localize("ストリーム応答を受信できませんでした。", "No streaming response was received."));
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
          if (generation.abortController.signal.aborted || !isGenerationActive(generation)) {
            return "aborted" as const;
          }
          // Network handoffs usually surface as TypeError, but some browsers
          // use AbortError when they tear down an existing SSE response.  Both
          // mean the request itself was not cancelled by the user, so resume
          // from the last event ID instead of treating the answer as failed.
          if (error instanceof TypeError || (error as { name?: string })?.name === "AbortError") {
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
        let reconnectAttempt = 0;
        while (isGenerationActive(generation)) {
          const result = await readStreamResponse(activeResponse);
          if (!isGenerationActive(generation)) return false;

          if (result === "completed") {
            if (revealCompletionPromise) await revealCompletionPromise;
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

          try {
            await waitForGenerationStreamReconnect(reconnectAttempt, generation.abortController.signal);
          } catch (error) {
            if (generation.abortController.signal.aborted || !isGenerationActive(generation)) return false;
            throw error;
          }
          reconnectAttempt += 1;
          if (!isGenerationActive(generation)) return false;

          const reconnectResponse = await openReconnectStream();
          if (reconnectResponse === "unavailable") {
            persistInterruptedStream(
              streamedText
                ? localize("ストリームを再開できませんでした。ここまでの応答を保存しました。", "The stream could not be resumed. The response received so far was saved.")
                : localize("ストリームを再開できませんでした。", "The stream could not be resumed."),
            );
            return false;
          }
          if (!reconnectResponse) {
            // A lost Wi-Fi connection can make the first few reconnects fail
            // even after the browser reports online. Keep the local progress
            // and continue retrying until the user stops the generation.
            continue;
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
        if (finalRevealTimerId !== null) {
          window.clearTimeout(finalRevealTimerId);
          finalRevealTimerId = null;
        }
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
      requestScrollToBottom,
    ],
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
          const response = await resilientFetch(
            `/api/chat_generation_stream?room_id=${encodeURIComponent(roomId)}`,
            {
              credentials: "same-origin",
              signal: generation.abortController.signal,
            },
            { timeoutMs: 0 },
          );
          if (response.ok) return response;

          // A 4xx response means the original request was not accepted (or the
          // session is no longer valid); retries cannot safely recreate a POST.
          if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) {
            return null;
          }
        } catch {
          if (generation.abortController.signal.aborted) return null;
        }
      }

      return null;
    },
    [isGenerationActive],
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
            text: localize("AIが応答を準備しています", "AI is preparing a response"),
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

      const userMessage: UiChatMessage = {
        id: nextMessageId("user", messageSeqRef),
        sender: "user",
        text: message,
        attachedFileNames: attachedFiles?.length ? attachedFiles.map((f) => f.name) : undefined,
      };
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
      notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: message, sender: "user" }));
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      writeStoredGenerationState({
        roomId,
        roomMode,
        lastEventId: 0,
        streamedText: "",
        updatedAt: Date.now(),
      });
      requestScrollToBottom();

      // 回答が1件も返らなかったターンの後始末。ユーザー発話ごと取り消してから
      // エラーを1件だけ表示するので、再送しても自分の発話が積み上がらない。
      // Clean up a turn that produced no answer: roll the user's own message back
      // and show a single error, so retrying never stacks up user bubbles.
      const handleUnansweredFailure = (errorMessage: string) => {
        if (!isGenerationActive(generation)) return;
        clearStoredGenerationState(roomId);
        rollbackUnansweredUserMessage(roomId, userMessage.id, message, options?.unsentInputText);
        appendAssistantErrorMessage(roomId, errorMessage);
      };

      const postChatMessage = () =>
        resilientFetch(
          "/api/chat",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({
              message,
              chat_room_id: roomId,
              model,
              use_personal_knowledge: personalKnowledgeEnabled,
              use_shared_prompts: sharedPromptsEnabled,
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

      try {
        let response = await postChatMessage();
        // ルームがサーバー上に無いだけなら、作り直して同じ本文をもう一度送る。
        // ここで諦めると、その画面からは二度とチャットを続けられなくなる。
        // When only the room is missing, recreate it and send the same message
        // once more; giving up here would leave the chat permanently unusable.
        if (response.status === 404) {
          const notFoundPayload = await readJsonBodySafe(response);
          const restored =
            isChatRoomNotFoundPayload(notFoundPayload) &&
            isGenerationActive(generation) &&
            (await restoreMissingChatRoom(roomId, message, roomMode));

          if (restored) {
            response = await postChatMessage();
          } else {
            handleUnansweredFailure(
              extractApiErrorMessage(
                notFoundPayload,
                localize("チャットの送信に失敗しました。", "The message could not be sent."),
                response.status,
              ),
            );
            return false;
          }
        }

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          return await consumeStreamingChatResponse(response, generation, {
            onUnansweredFailure: handleUnansweredFailure,
          });
        }

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

        if (data.response && isGenerationActive(generation)) {
          notifyStoredHistoryWriteIssue(appendStoredHistory(roomId, { text: data.response, sender: "bot" }));
          applyRoomTitleUpdate(roomId, data.roomTitle);
        }
        clearStoredGenerationState(roomId);
        // 回答が届いても画面は動かさない。見落とすと困るエラーだけ下端へ送る。
        // An arriving answer never moves the view; only an error, which must not
        // be missed, still pulls the view to the bottom.
        return true;
      } catch (error) {
        if (generation.abortController.signal.aborted) {
          if (isGenerationActive(generation)) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return removeThinkingMessages(previous);
            });
          }
          return false;
        }

        // The POST may have reached the server even when the client loses the
        // response during a Wi-Fi/mobile handoff. Do not resend it (which could
        // create a duplicate turn); attach to the generation the server already
        // started instead.
        const recoveredResponse = await recoverInitialGenerationStream(roomId, generation);
        if (recoveredResponse && isGenerationActive(generation)) {
          return consumeStreamingChatResponse(recoveredResponse, generation, {
            onUnansweredFailure: handleUnansweredFailure,
          });
        }

        handleUnansweredFailure(error instanceof Error ? error.message : String(error));
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
      personalKnowledgeEnabled,
      sharedPromptsEnabled,
      recoverInitialGenerationStream,
      refreshActivePath,
      releaseGeneration,
      removeThinkingMessages,
      requestScrollToBottom,
      restoreMissingChatRoom,
      rollbackUnansweredUserMessage,
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
      const initialThinkingState = getInitialThinkingState(
        personalKnowledgeEnabled,
        sharedPromptsEnabled,
        localeRef.current,
      );
      const thinkingMsg: UiChatMessage = {
        id: nextMessageId("thinking", messageSeqRef),
        sender: "thinking",
        ...initialThinkingState,
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
      requestScrollToBottom();

      // 編集した発話も回答が返らなければサーバー側で破棄される。画面にだけ残すと
      // 送り直すたびに自分の発話が積み上がるため、同じように取り消す。
      // An edited message is discarded server-side when no answer comes back, so
      // roll it back here too instead of stacking it on every retry.
      const handleUnansweredFailure = (errorMessage: string) => {
        if (!isGenerationActive(generation)) return;
        clearStoredGenerationState(roomId);
        rollbackUnansweredUserMessage(roomId, userMsg.id, newMessage);
        appendAssistantErrorMessage(roomId, errorMessage);
      };

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
          if (isGenerationActive(generation)) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId || !isGenerationActive(generation)) return previous;
              return removeThinkingMessages(previous);
            });
          }
          return;
        }
        handleUnansweredFailure(error instanceof Error ? error.message : String(error));
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
      personalKnowledgeEnabled,
      sharedPromptsEnabled,
      refreshActivePath,
      releaseGeneration,
      removeThinkingMessages,
      requestScrollToBottom,
      rollbackUnansweredUserMessage,
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
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      writeStoredGenerationState({
        roomId,
        roomMode: currentRoomMode,
        lastEventId: 0,
        streamedText: "",
        updatedAt: Date.now(),
      });
      requestScrollToBottom();

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
      personalKnowledgeEnabled,
      sharedPromptsEnabled,
      refreshActivePath,
      releaseGeneration,
      removeThinkingMessages,
      requestScrollToBottom,
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
