// チャット生成 SSE を1本読み切るランタイム。React には依存せず、画面更新と
// 永続化はすべて注入されたポート越しに行う。文字送り（等速ペーシング・語単位の
// フェード・最終フェードの待ち合わせ）と再接続バックオフはユーザーに見える挙動
// なので、hook から移設したロジックをそのままの順序で保っている。
// Runtime that reads one chat-generation SSE stream to the end. It does not
// depend on React: every screen update and persistence write goes through an
// injected port. The reveal pacing (constant pace, word-level fade, waiting for
// the final fade) and the reconnect backoff are user-visible, so the logic
// moved out of the hook keeps its original order.

import { getStreamingGenerativeUiDisplayText, isGenerativeUiPending, updateStreamingTextPart } from "./generative_ui_stream";
import {
  interpretGenerationStreamEvent,
  type GenerationStreamAction,
  type StreamLocalize,
} from "./generation_stream_events";
import {
  BROWSER_RECONNECT_RUNTIME,
  isUnrecoverableStreamStatus,
  waitForGenerationStreamReconnect,
  type GenerationStreamReconnectRuntime,
} from "./generation_stream_reconnect";
import { removeThinkingMessages } from "./home_page_controller_utils";
import { rememberStreamEventId } from "./message_window";
import { createSseBlockDecoder } from "./sse_block_decoder";
import { advanceStreamPace, clampToCodePointBoundary, createStreamPace } from "./stream_smoothing";
import { normalizeCitationChipStreamBoundary, splitStreamDisplayText } from "./stream_display_text";
import { parseStreamEventBlock } from "./streaming";
import {
  WORD_REVEAL_DURATION_MS,
  WORD_REVEAL_MAX_LAG_MS,
  clampToRevealChunkBoundary,
  clampToWordBoundary,
} from "./streaming_word_reveal";
import type {
  ChatGenerationPhase,
  ChatMessagePart,
  StoredGenerationState,
  StoredHistoryEntry,
  UiChatMessage,
} from "./types";

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

export type GenerationStreamTimers = {
  now: () => number;
  setTimeout: (handler: () => void, ms: number) => number;
  clearTimeout: (timerId: number) => void;
  requestAnimationFrame: (handler: () => void) => number;
  cancelAnimationFrame: (handle: number) => void;
};

export const BROWSER_STREAM_TIMERS: GenerationStreamTimers = {
  now: () => performance.now(),
  setTimeout: (handler, ms) => window.setTimeout(handler, ms),
  clearTimeout: (timerId) => window.clearTimeout(timerId),
  requestAnimationFrame: (handler) => window.requestAnimationFrame(handler),
  cancelAnimationFrame: (handle) => window.cancelAnimationFrame(handle),
};

export type GenerationStreamMessagesPort = {
  // 対象ルーム・対象生成が現役の間だけメッセージ配列へ反映する。
  // Apply to the message list only while the room and generation are current.
  updateActiveMessages: (updater: (previous: UiChatMessage[]) => UiChatMessage[]) => void;
  createMessageId: (prefix: string) => string;
  // エラー吹き出しの追加（ルーム一致だけを条件とし、末尾へ送る）。
  // Append an error bubble (guarded on the room only) and scroll to it.
  appendErrorMessage: (message: string) => void;
  applyRoomTitle: (title: unknown) => void;
};

export type GenerationStreamStoragePort = {
  readGenerationState: () => StoredGenerationState | null;
  updateGenerationState: (updates: Partial<Pick<StoredGenerationState, "lastEventId" | "streamedText">>) => void;
  clearGenerationState: () => void;
  persistAssistantAnswer: (entry: StoredHistoryEntry) => void;
};

export type GenerationStreamHost = {
  roomId: string;
  abortSignal: AbortSignal;
  // この生成がまだ現役か（別の生成に置き換わっていないか）。
  // Whether this generation is still the active one.
  isActive: () => boolean;
  lastEventIdByRoom: Map<string, number>;
  localize: StreamLocalize;
  messages: GenerationStreamMessagesPort;
  storage: GenerationStreamStoragePort;
  timers?: GenerationStreamTimers;
  reconnectRuntime?: GenerationStreamReconnectRuntime;
  // Last-Event-ID 付きでストリームを開き直す。ネットワーク失敗は例外で伝える。
  // Reopen the stream with Last-Event-ID; network failures surface as throws.
  openStream: (lastEventId: number) => Promise<Response>;
  // 1文字も返らなかったターンの後始末を呼び出し側へ委譲する。
  // Delegate cleanup of a turn that produced no answer at all to the caller.
  onUnansweredFailure?: (message: string) => void;
};

type PendingFinalization = {
  finalText: string;
  persist: boolean;
  parts?: ChatMessagePart[];
};

type StreamSessionState = {
  streamingMessageId: string | null;
  streamedText: string;
  streamingParts: ChatMessagePart[] | undefined;
  pendingFinalization: PendingFinalization | null;
  hasSeparatedInstantPrefix: boolean;
};

type StreamProgressState = {
  completed: boolean;
  streamError: string | null;
};

type StreamReadResult =
  | "completed"
  | "interrupted"
  | "aborted"
  | "inactive"
  | { status: "error"; message: string };

// localStorage への進行状態書き込みをスロットルする。
// Throttles progress writes to localStorage.
function createStoredGenerationStateSync(
  storage: GenerationStreamStoragePort,
  timers: GenerationStreamTimers,
  readStreamedText: () => string,
) {
  let timerId: number | null = null;
  let pendingLastEventId = 0;
  let hasPendingStreamedText = false;

  const flush = () => {
    timerId = null;
    if (pendingLastEventId <= 0 && !hasPendingStreamedText) return;
    const updates = {
      ...(pendingLastEventId > 0 ? { lastEventId: pendingLastEventId } : {}),
      ...(hasPendingStreamedText ? { streamedText: readStreamedText() } : {}),
    };
    pendingLastEventId = 0;
    hasPendingStreamedText = false;
    storage.updateGenerationState(updates);
  };

  const schedule = () => {
    if (timerId !== null) return;
    timerId = timers.setTimeout(flush, STORED_GENERATION_STATE_SYNC_INTERVAL_MS);
  };

  return {
    noteLastEventId(eventId: number) {
      pendingLastEventId = eventId;
      schedule();
    },
    noteStreamedText() {
      hasPendingStreamedText = true;
      schedule();
    },
    // 途中終了時も保留分を確定させる。クリア済みの場合は
    // updateGenerationState が no-op になるため復活はしない。
    // On any exit, settle pending work. If the stored state was already
    // cleared, updateGenerationState is a no-op, so nothing revives.
    settle() {
      if (timerId !== null) {
        timers.clearTimeout(timerId);
      }
      flush();
    },
  };
}

// チャンク描画・確定描画・思考ステータス更新をまとめた表示側。1フレーム1回へ
// 間引き、上限付きの等速ペースで表示文字数を進める。
// The rendering side: chunk renders, finalization and thinking-status updates.
// It coalesces to one render per frame and advances the visible length at a
// capped, steady pace.
function createStreamRenderer(
  host: GenerationStreamHost,
  state: StreamSessionState,
  timers: GenerationStreamTimers,
  initialPacedLength: number,
) {
  const { messages, storage } = host;
  const streamPace = createStreamPace(initialPacedLength, timers.now());

  let chunkRenderRafId: number | null = null;
  let finalRevealTimerId: number | null = null;
  let revealCompletionPromise: Promise<void> | null = null;
  let resolveRevealCompletion: (() => void) | null = null;

  const cancelRender = () => {
    if (chunkRenderRafId !== null) {
      timers.cancelAnimationFrame(chunkRenderRafId);
      chunkRenderRafId = null;
    }
  };

  const scheduleRender = () => {
    if (chunkRenderRafId !== null) return;
    chunkRenderRafId = timers.requestAnimationFrame(() => flushChunkRender());
  };

  const ensureStreamingMessage = () => {
    if (state.streamingMessageId) return state.streamingMessageId;
    state.streamingMessageId = messages.createMessageId("assistant-stream");
    const newId = state.streamingMessageId;
    const displayText = getStreamingGenerativeUiDisplayText(state.streamedText);
    const displayParts = updateStreamingTextPart(state.streamingParts, displayText);
    const generativeUiPending = isGenerativeUiPending(state.streamedText, state.streamingParts);

    messages.updateActiveMessages((previous) => [
      ...removeThinkingMessages(previous),
      {
        id: newId,
        sender: "assistant",
        text: displayText,
        streaming: true,
        generativeUiPending,
        ...(displayParts ? { parts: displayParts } : {}),
      },
    ]);
    return newId;
  };

  const finalizeStreamingMessage = (
    finalText: string,
    persist = true,
    parts?: ChatMessagePart[],
    // 途中までの回答として保存されたターンに印を付け、続きを生成する導線を出す。
    // Mark a turn saved as a partial answer so the "continue" affordance can appear.
    markPartial = false,
  ) => {
    // 確定テキストを保留中の途中描画で上書きしないようにキャンセルする。
    // Cancel any pending partial render so it cannot overwrite the final text.
    cancelRender();
    const finalDisplayText = finalText || getStreamingGenerativeUiDisplayText(state.streamedText);
    const resolvedParts =
      Array.isArray(parts) && parts.length > 0 ? parts : updateStreamingTextPart(state.streamingParts, finalDisplayText);
    const hasParts = Array.isArray(resolvedParts) && resolvedParts.length > 0;
    const persistAnswer = () => {
      if (persist && finalDisplayText && host.isActive()) {
        storage.persistAssistantAnswer({
          text: finalDisplayText,
          sender: "bot",
          ...(hasParts ? { parts: resolvedParts } : {}),
        });
      }
      storage.clearGenerationState();
    };

    if (!state.streamingMessageId) {
      if (finalDisplayText || hasParts) {
        messages.updateActiveMessages((previous) => [
          ...removeThinkingMessages(previous),
          {
            id: messages.createMessageId("assistant"),
            sender: "assistant",
            text: finalDisplayText,
            ...(hasParts ? { parts: resolvedParts } : {}),
            ...(markPartial ? { partial: true } : {}),
          },
        ]);
      } else {
        messages.updateActiveMessages((previous) => removeThinkingMessages(previous));
      }
      persistAnswer();
      return;
    }

    const streamId = state.streamingMessageId;
    messages.updateActiveMessages((previous) =>
      removeThinkingMessages(previous).map((message) =>
        message.id === streamId
          ? {
              ...message,
              text: finalDisplayText || message.text,
              ...(hasParts ? { parts: resolvedParts } : {}),
              streaming: false,
              generativeUiPending: false,
              partial: markPartial,
            }
          : message,
      ),
    );
    persistAnswer();
  };

  const finishPendingFinalization = () => {
    const pending = state.pendingFinalization;
    if (!pending) return;
    state.pendingFinalization = null;
    finalizeStreamingMessage(pending.finalText, pending.persist, pending.parts);
    resolveRevealCompletion?.();
    resolveRevealCompletion = null;
  };

  // 表示位置を1フレーム分進め、チャンク境界→語境界→引用チップ境界へ丸める。
  // Advance one frame, then round to a chunk, word and citation-chip boundary.
  const resolveDisplayLength = (pacedText: string, frameNow: number) => {
    const smoothedLength = clampToCodePointBoundary(pacedText, advanceStreamPace(streamPace, pacedText.length, frameNow));
    // 表示はチャンク境界まで巻き戻し、さらに語境界へ合わせる。文字単位で
    // 伸ばすと生成中の行が毎フレーム折り返し直しになり、読んでいる文字が
    // 動いてしまう（スマホで顕著）。かたまり単位で伸ばせば折り返しの変化が
    // まばらになり、フェードインも1かたまりずつはっきり見える。
    // Pull the visible length back to a chunk boundary, then to a word
    // boundary. Growing character by character re-wraps the streaming line
    // every frame and shifts the characters being read (worst on phones);
    // growing in chunks makes re-wraps rare and each fade-in legible.
    const displayLength = normalizeCitationChipStreamBoundary(
      pacedText,
      clampToCodePointBoundary(pacedText, clampToWordBoundary(pacedText, clampToRevealChunkBoundary(pacedText, smoothedLength))),
    );
    // チップ内部のHTML文字数をペーシング待ちにしない。完成済みチップを一度に
    // 表示したあとは、その直後の本文から通常速度で再開する。
    // Skip markup bytes after atomically revealing a complete chip, then
    // resume normal pacing with the text immediately after it.
    if (displayLength > streamPace.length) streamPace.length = displayLength;
    return { displayLength, smoothedLength };
  };

  const flushChunkRender = () => {
    chunkRenderRafId = null;
    const streamId = state.streamingMessageId;
    if (!streamId) return;
    const separatedDisplayText = splitStreamDisplayText(getStreamingGenerativeUiDisplayText(state.streamedText));
    const frameNow = timers.now();
    if (!state.hasSeparatedInstantPrefix && separatedDisplayText.instantPrefix) {
      // 不完全だった検索トレースが閉じた瞬間、そこまでHTMLへ費やしていた進捗を
      // 本文へ持ち越さない。本文は先頭から通常のテンポで表示する。
      // When an incomplete trace becomes complete, do not carry progress
      // spent on its raw HTML into the answer body. Pace the body from zero.
      streamPace.length = 0;
      streamPace.rate = 0;
      streamPace.lastTime = frameNow;
      state.hasSeparatedInstantPrefix = true;
    }
    const { displayLength, smoothedLength } = resolveDisplayLength(separatedDisplayText.pacedText, frameNow);
    const displayText = [separatedDisplayText.instantPrefix, separatedDisplayText.pacedText.slice(0, displayLength)].join("");
    renderStreamingText(streamId, displayText);

    if (smoothedLength < separatedDisplayText.pacedText.length) {
      scheduleRender();
      return;
    }
    if (state.pendingFinalization && finalRevealTimerId === null) {
      // 最終文字を streaming=true のDOMへ一度描画した後、そのCSSアニメーションが
      // 完了する時間を確保してから完成状態へ切り替える。
      // Render the final characters into the streaming DOM once, then give
      // their CSS animation time to finish before switching to the clean
      // completed markup.
      finalRevealTimerId = timers.setTimeout(() => {
        finalRevealTimerId = null;
        finishPendingFinalization();
      }, STREAM_REVEAL_SETTLE_MS);
    }
  };

  const renderStreamingText = (streamId: string, displayText: string) => {
    const displayParts = updateStreamingTextPart(state.streamingParts, displayText);
    const generativeUiPending = isGenerativeUiPending(state.streamedText, state.streamingParts);

    messages.updateActiveMessages((previous) =>
      previous.map((message) =>
        message.id === streamId
          ? {
              ...message,
              text: displayText,
              streaming: true,
              generativeUiPending,
              ...(displayParts ? { parts: displayParts } : {}),
            }
          : message,
      ),
    );
  };

  return {
    scheduleRender,
    cancelRender,
    ensureStreamingMessage,
    finalizeStreamingMessage,

    updateThinkingStatus(statusText: string, generationPhase: ChatGenerationPhase = "preparing") {
      messages.updateActiveMessages((previous) =>
        previous.map((message) =>
          message.sender === "thinking" ? { ...message, text: statusText, generationPhase } : message,
        ),
      );
    },

    // 最終応答を表示キューへ渡し、未表示分と最後のフェードが完了してから
    // streaming=false にする。高速応答でも末尾が一括表示されなくなる。
    // Feed the final response through the display queue and only mark it
    // complete after the remaining text and fade have drained.
    queueFinalization(finalText: string, persist = true, parts?: ChatMessagePart[]) {
      state.pendingFinalization = { finalText, persist, parts };
      if (!revealCompletionPromise) {
        revealCompletionPromise = new Promise<void>((resolve) => {
          resolveRevealCompletion = resolve;
        });
      }
      scheduleRender();
    },

    // パーツ更新はテキストの書き換えを伴うため、ペーシングせず全文を出す。
    // Parts updates rewrite the text, so show it in full without pacing.
    applyPartsUpdate(displayText: string, parts: ChatMessagePart[] | null) {
      const separatedDisplayText = splitStreamDisplayText(displayText);
      streamPace.length = separatedDisplayText.pacedText.length;
      state.hasSeparatedInstantPrefix ||= Boolean(separatedDisplayText.instantPrefix);
      if (parts) {
        state.streamingParts = updateStreamingTextPart(parts, displayText);
      }
      const streamId = ensureStreamingMessage();
      renderStreamingText(streamId, displayText);
    },

    revealCompletion() {
      return revealCompletionPromise;
    },

    dispose() {
      cancelRender();
      if (finalRevealTimerId !== null) {
        timers.clearTimeout(finalRevealTimerId);
        finalRevealTimerId = null;
      }
    },
  };
}

// 復元済みの進行状態から、記憶している最終イベントIDを引き上げる。
// Raise the remembered last event id from the persisted progress state.
function restoreRememberedLastEventId(host: GenerationStreamHost, stored: StoredGenerationState | null): void {
  if (!stored || stored.lastEventId <= 0) return;
  const remembered = host.lastEventIdByRoom.get(host.roomId) ?? 0;
  if (stored.lastEventId > remembered) {
    host.lastEventIdByRoom.set(host.roomId, stored.lastEventId);
  }
}

export function consumeGenerationStream(response: Response, host: GenerationStreamHost): Promise<boolean> {
  const timers = host.timers ?? BROWSER_STREAM_TIMERS;
  const reconnectRuntime = host.reconnectRuntime ?? BROWSER_RECONNECT_RUNTIME;
  const { roomId } = host;

  const storedGeneration = host.storage.readGenerationState();
  restoreRememberedLastEventId(host, storedGeneration);

  // 等速ペーシングの状態。復元テキストはリプレイせず即時表示する。
  // Constant-pace state. Restored text shows instantly instead of being replayed.
  const restoredText = storedGeneration?.streamedText ?? "";
  const initialDisplayText = splitStreamDisplayText(getStreamingGenerativeUiDisplayText(restoredText));
  const state: StreamSessionState = {
    streamingMessageId: null,
    streamedText: restoredText,
    streamingParts: undefined,
    pendingFinalization: null,
    hasSeparatedInstantPrefix: Boolean(initialDisplayText.instantPrefix),
  };

  const renderer = createStreamRenderer(host, state, timers, initialDisplayText.pacedText.length);
  const storedStateSync = createStoredGenerationStateSync(host.storage, timers, () => state.streamedText);

  // TextDecoder は再接続をまたいで共有する（分割されたマルチバイト文字を保つ）。
  // The TextDecoder is shared across reconnects so split multibyte characters survive.
  const textDecoder = new TextDecoder();

  const persistInterruptedStream = (message: string) => {
    if (state.streamedText.trim()) {
      renderer.finalizeStreamingMessage(
        getStreamingGenerativeUiDisplayText(state.streamedText),
        true,
        state.streamingParts,
      );
      host.messages.appendErrorMessage(message);
      return;
    }
    // 1文字も届いていない = このターンには回答がない。呼び出し側が
    // ユーザー発話の取り消しまで含めて後始末できるよう委譲する。
    // Nothing arrived at all, so this turn has no answer. Let the caller
    // clean up, including rolling back the user's own message.
    const handleUnansweredFailure = host.onUnansweredFailure;
    if (handleUnansweredFailure) {
      handleUnansweredFailure(message);
      return;
    }
    host.messages.appendErrorMessage(message);
  };

  const applyStreamAction = (action: GenerationStreamAction, progress: StreamProgressState) => {
    switch (action.kind) {
      case "ignored":
        return;
      case "chunk":
        renderer.ensureStreamingMessage();
        state.streamedText += action.text;
        storedStateSync.noteStreamedText();
        renderer.scheduleRender();
        return;
      case "parts_updated":
        // 直後に最新テキストで即時描画するため、保留中のチャンク描画は破棄する。
        // Drop the pending chunk render; the immediate update below already
        // carries the latest text.
        renderer.cancelRender();
        renderer.applyPartsUpdate(action.displayText, action.parts);
        return;
      case "thinking_status":
        renderer.updateThinkingStatus(action.text, action.phase);
        return;
      case "done":
        progress.completed = true;
        host.messages.applyRoomTitle(action.roomTitle);
        renderer.ensureStreamingMessage();
        state.streamedText = action.responseText;
        renderer.queueFinalization(action.responseText, true, action.parts);
        host.lastEventIdByRoom.delete(roomId);
        return;
      case "empty_answer":
        // 空の完了は「回答なし」。空の吹き出しを残さずエラーとして扱う。
        // An empty completion means no answer: treat it as an error instead
        // of leaving a blank bubble behind.
        progress.completed = false;
        host.messages.applyRoomTitle(action.roomTitle);
        progress.streamError = action.message;
        host.lastEventIdByRoom.delete(roomId);
        host.storage.clearGenerationState();
        return;
      case "incomplete":
        progress.completed = true;
        host.messages.applyRoomTitle(action.roomTitle);
        renderer.finalizeStreamingMessage(action.finalText, false, action.parts, true);
        host.messages.appendErrorMessage(action.message);
        host.lastEventIdByRoom.delete(roomId);
        host.storage.clearGenerationState();
        return;
      case "aborted":
        progress.completed = true;
        renderer.finalizeStreamingMessage(action.finalText, false, action.parts);
        host.storage.clearGenerationState();
        return;
      case "error":
        progress.streamError = action.message;
        return;
    }
  };

  const processBlock = (block: string, progress: StreamProgressState) => {
    const parsed = parseStreamEventBlock(block);
    if (!parsed) return;
    if (!host.isActive()) return;

    if (!rememberStreamEventId(host.lastEventIdByRoom, roomId, parsed.id)) return;
    if (typeof parsed.id === "number" && parsed.id > 0) {
      storedStateSync.noteLastEventId(parsed.id);
    }

    applyStreamAction(
      interpretGenerationStreamEvent(parsed, { streamedText: state.streamedText, localize: host.localize }),
      progress,
    );
  };

  const readStreamResponse = async (streamResponse: Response): Promise<StreamReadResult> => {
    if (!streamResponse.body) {
      throw new Error(host.localize("ストリーム応答を受信できませんでした。", "No streaming response was received."));
    }

    const reader = streamResponse.body.getReader();
    const blockDecoder = createSseBlockDecoder(textDecoder);
    const progress: StreamProgressState = { completed: false, streamError: null };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (!host.isActive()) return "inactive";
        blockDecoder.push(value, done).forEach((block) => processBlock(block, progress));

        if (progress.streamError) break;
        if (done) break;
      }
    } catch (error) {
      if (host.abortSignal.aborted || !host.isActive()) {
        return "aborted";
      }
      // Network handoffs usually surface as TypeError, but some browsers
      // use AbortError when they tear down an existing SSE response.  Both
      // mean the request itself was not cancelled by the user, so resume
      // from the last event ID instead of treating the answer as failed.
      if (error instanceof TypeError || (error as { name?: string })?.name === "AbortError") {
        return "interrupted";
      }
      throw error;
    } finally {
      reader.cancel().catch(() => {
        // no-op
      });
    }

    if (progress.streamError) {
      return { status: "error", message: progress.streamError };
    }

    return progress.completed ? "completed" : "interrupted";
  };

  const openReconnectStream = async (): Promise<Response | "unavailable" | null> => {
    const lastEventId = host.lastEventIdByRoom.get(roomId);
    if (typeof lastEventId !== "number" || lastEventId <= 0) return null;

    try {
      const reconnectResponse = await host.openStream(lastEventId);
      if (!reconnectResponse.ok) {
        return isUnrecoverableStreamStatus(reconnectResponse.status) ? "unavailable" : null;
      }
      return reconnectResponse;
    } catch {
      return null;
    }
  };

  const runStreamWithReconnects = async (initialResponse: Response): Promise<boolean> => {
    let activeResponse = initialResponse;
    let reconnectAttempt = 0;

    while (host.isActive()) {
      const result = await readStreamResponse(activeResponse);
      if (!host.isActive()) return false;

      if (result === "completed") {
        const revealCompletion = renderer.revealCompletion();
        if (revealCompletion) await revealCompletion;
        return true;
      }

      if (result === "aborted" || result === "inactive") return false;

      if (typeof result === "object" && result.status === "error") {
        persistInterruptedStream(state.streamedText ? `${result.message} ここまでの応答を保存しました。` : result.message);
        return false;
      }

      try {
        await waitForGenerationStreamReconnect(reconnectAttempt, host.abortSignal, reconnectRuntime);
      } catch (error) {
        if (host.abortSignal.aborted || !host.isActive()) return false;
        throw error;
      }
      reconnectAttempt += 1;
      if (!host.isActive()) return false;

      const reconnectResponse = await openReconnectStream();
      if (reconnectResponse === "unavailable") {
        persistInterruptedStream(
          state.streamedText
            ? host.localize(
                "ストリームを再開できませんでした。ここまでの応答を保存しました。",
                "The stream could not be resumed. The response received so far was saved.",
              )
            : host.localize("ストリームを再開できませんでした。", "The stream could not be resumed."),
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
  };

  if (state.streamedText) {
    renderer.ensureStreamingMessage();
  }

  return (async () => {
    try {
      return await runStreamWithReconnects(response);
    } finally {
      renderer.dispose();
      storedStateSync.settle();
    }
  })();
}
