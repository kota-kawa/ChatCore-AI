// チャット生成 SSE を1本読み切るランタイム。React には依存せず、画面更新と
// 永続化はすべて注入されたポート越しに行う。文字送り（等速ペーシング・語単位の
// フェード・最終フェードの待ち合わせ）と再接続バックオフはユーザーに見える挙動
// なので、hook から移設したロジックをそのままの順序で保っている。
// Runtime that reads one chat-generation SSE stream to the end. It does not
// depend on React: every screen update and persistence write goes through an
// injected port. The reveal pacing (constant pace, word-level fade, waiting for
// the final fade) and the reconnect backoff are user-visible, so the logic
// moved out of the hook keeps its original order.

import { isAnswerTracePart, isSameAnswerTrace, withAnswerTracePart } from "./answer_trace";
import {
  generativeUiFenceKind,
  getStreamingGenerativeUiDisplayText,
  isGenerativeUiPending,
  updateStreamingTextPart,
} from "./generative_ui_stream";
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
import {
  FINAL_REVEAL_WINDOW_MS,
  advanceStreamPace,
  advanceStreamPaceToFinish,
  clampToCodePointBoundary,
  createStreamPace,
} from "./stream_smoothing";
import { normalizeCitationChipStreamBoundary } from "./stream_display_text";
import { parseStreamEventBlock } from "./streaming";
import {
  WORD_REVEAL_DURATION_MS,
  WORD_REVEAL_MAX_LAG_MS,
  clampToRevealChunkBoundary,
  clampToWordBoundary,
} from "./streaming_word_reveal";
import type {
  AnswerTraceV1,
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

// 再接続の「進捗なし」試行上限（生涯合計ではない）。再接続した応答で新しい
// イベント（本文・進捗）を1件でも受け取れればカウントはリセットされる。
// 接続が 200 で開くだけでは成功と数えない。バックオフは 15 秒で頭打ちになるため、
// この回数で約 105 秒粘ってから諦める。上限が無いと、復旧しない切断（ヘッダーだけ
// 返して本文を送らないプロキシなど）で「思考中」のまま無限に空転し、エラー表示も
// 生成ガードの解放も起きなくなる。接続の成否だけでリセットすると、200 で開いて
// すぐ空で閉じる応答が待ち 0ms のまま無限に続く。生涯合計にしてしまうと、長時間
// ターンで回線が不安定でも正常に復旧し続けているケースまで、通算回数を使い切った
// だけで打ち切られてしまう。
// Upper bound on reconnects *without progress* (not a lifetime total): the
// count resets to zero whenever a reconnected response delivers at least one
// new event (text or progress). Merely opening with a 200 does not count as
// success. The backoff tops out at 15s, so this keeps trying for roughly 105
// seconds before giving up. Without a bound, a drop that never recovers (e.g.
// a proxy that returns headers but no events) spins forever: no error is
// surfaced and the generation guard is never released. Resetting on the
// connection alone would let a 200 that closes empty loop forever at a 0ms
// wait. Treating it as a lifetime total instead would cut off a long turn that
// keeps recovering fine over a flaky connection, just because the lifetime
// count ran out.
const MAX_GENERATION_STREAM_RECONNECT_ATTEMPTS = 12;

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
  updateGenerationState: (
    updates: Partial<Pick<StoredGenerationState, "lastEventId" | "streamedText" | "generationId" | "answerTrace">>,
  ) => void;
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
  openStream: (lastEventId: number, generationId?: string) => Promise<Response>;
  generationId?: string;
  onGenerationId?: (generationId: string) => void;
  // 1文字も返らなかったターンの後始末を呼び出し側へ委譲する。
  // Delegate cleanup of a turn that produced no answer at all to the caller.
  onUnansweredFailure?: (message: string) => void;
};

type PendingFinalization = {
  finalText: string;
  persist: boolean;
  parts?: ChatMessagePart[];
  assistantMessageId?: number;
};

type StreamSessionState = {
  streamingMessageId: string | null;
  streamedText: string;
  // 確定前に先行して見せている表示専用の下書き。保存・復元の対象は streamedText だけで、
  // 下書きは含めない。
  // The display-only draft shown ahead of confirmation. Only streamedText is stored and restored;
  // the draft is never part of it.
  draftText: string;
  // 下書きが取り消された時点の確定済み本文の長さ。取り消されたあとも、確定した本文が下書きの長さに
  // 追いつくまでは下書きの残りを表示に残し、表示が縮んで再表示されるちらつきを防ぐ。null は取り消し前。
  // The confirmed length when the draft was discarded. The rest of the draft stays on screen until
  // the confirmed text catches up with it, so the display never shrinks and replays. null before a discard.
  draftDiscardedAt: number | null;
  // 吹き出しが下書きだけで作られ、確定した本文がまだ無いか。下書きが捨てられたときに吹き出しごと取り除く。
  // Whether the bubble was created by a draft alone and holds no confirmed text yet, so a discarded
  // draft takes the bubble with it.
  messageHeldByDraft: boolean;
  streamingParts: ChatMessagePart[] | undefined;
  // 受信済みの回答までのステップ（全体スナップショット）。本文とは別に持ち、表示のたびにパーツ列の先頭へ載せる。
  // 生成中のパーツ更新（response_parts_updated）はこれを知らないので、パーツ側に混ぜると更新で消えてしまう。
  // The steps to the answer received so far (a whole snapshot). Kept apart from the prose and laid at the head
  // of the part list on every render: the generation-time parts updates (response_parts_updated) do not know it,
  // so mixing it into those parts would let an update erase it.
  answerTrace: AnswerTraceV1 | null;
  // 吹き出しが実行記録だけを見せていて、その下に思考中の表示を残している間は true。本文か下書きが
  // 加わった時点で思考中の表示を外す。
  // True while the bubble shows only the execution record and the thinking indicator stays below it;
  // the indicator is removed once prose or a draft joins the bubble.
  thinkingKeptBelowMessage: boolean;
  pendingFinalization: PendingFinalization | null;
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

// 画面に出す本文。取り消された下書きは、確定した本文が追いついた分だけ短くなる。
// The text to show; a discarded draft shortens by as much as the confirmed text has caught up.
function readStreamShownText(state: Pick<StreamSessionState, "streamedText" | "draftText" | "draftDiscardedAt">) {
  if (state.draftDiscardedAt === null) return `${state.streamedText}${state.draftText}`;
  const confirmedSinceDiscard = state.streamedText.length - state.draftDiscardedAt;
  return `${state.streamedText}${state.draftText.slice(Math.max(confirmedSinceDiscard, 0))}`;
}

// 下書きを捨てる。
// Drop the draft entirely.
function clearStreamDraft(state: Pick<StreamSessionState, "draftText" | "draftDiscardedAt">) {
  state.draftText = "";
  state.draftDiscardedAt = null;
}

// localStorage への進行状態書き込みをスロットルする。
// Throttles progress writes to localStorage.
function createStoredGenerationStateSync(
  storage: GenerationStreamStoragePort,
  timers: GenerationStreamTimers,
  readStreamedText: () => string,
  readAnswerTrace: () => AnswerTraceV1 | null,
) {
  let timerId: number | null = null;
  let pendingLastEventId = 0;
  let hasPendingStreamedText = false;
  let hasPendingAnswerTrace = false;

  const flush = () => {
    timerId = null;
    if (pendingLastEventId <= 0 && !hasPendingStreamedText && !hasPendingAnswerTrace) return;
    // 実行記録は最後のイベント ID と同じ書き込みで保存する。再接続は ID より後のイベントしか再送しないので、
    // ID だけが進んで実行記録が欠けた状態を作らない。
    // The execution record is saved in the same write as the last event id. A reconnect only replays events
    // after that id, so the id must never run ahead of a record that is missing.
    const updates = {
      ...(pendingLastEventId > 0 ? { lastEventId: pendingLastEventId } : {}),
      ...(hasPendingStreamedText ? { streamedText: readStreamedText() } : {}),
      // 実行記録が無くなった場合は、保存済みの記録も消す。
      // When the record is gone, the stored one is removed as well.
      ...(hasPendingAnswerTrace ? { answerTrace: readAnswerTrace() ?? undefined } : {}),
    };
    pendingLastEventId = 0;
    hasPendingStreamedText = false;
    hasPendingAnswerTrace = false;
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
    noteAnswerTrace() {
      hasPendingAnswerTrace = true;
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
  // done 受信後の早送りの締め切りと、rAF が止まっても締め切りで描画を進める保険のタイマー。
  // Deadline of the post-"done" fast-forward, and a fallback timer that drives
  // the render at the deadline even when rAF is paused (a hidden tab).
  let finalRevealDeadline: number | null = null;
  let finalRevealDeadlineTimerId: number | null = null;
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

  // 画面に出す本文は、確定した本文の後ろに下書きを続けたもの。
  // What the screen shows is the confirmed text followed by the draft.
  const readShownText = () => readStreamShownText(state);

  // 本文のパーツへ、受信済みの実行記録を先頭に載せる。実行記録だけがあり本文のパーツが無いときも、
  // 本文を落とさないよう text パーツを添える。
  // Lay the received execution record at the head of the body parts. When there is a record but no body
  // part yet, a text part is added so the prose is not dropped.
  const composeParts = (displayText: string, isFinalText = false): ChatMessagePart[] | undefined => {
    const bodyParts = updateStreamingTextPart(state.streamingParts, displayText, isFinalText);
    if (!state.answerTrace) return bodyParts;
    return withAnswerTracePart(bodyParts ?? (displayText ? [{ type: "text", text: displayText }] : []), state.answerTrace);
  };

  // 実行記録だけの吹き出しを、思考中の表示の上に作る。本文より先に届いた「回答までのステップ」を見せるため。
  // 思考中の表示は残し、本文か下書きが加わった時に外す。
  // Create a bubble holding only the execution record, above the thinking indicator, so steps to the
  // answer that arrive before the prose are visible. The indicator stays and is removed once prose or a
  // draft joins the bubble.
  const ensureRecordMessage = () => {
    if (state.streamingMessageId || !state.answerTrace) return;
    state.streamingMessageId = messages.createMessageId("assistant-stream");
    const newId = state.streamingMessageId;
    const recordParts = withAnswerTracePart([], state.answerTrace);
    state.thinkingKeptBelowMessage = true;
    messages.updateActiveMessages((previous) => [
      ...removeThinkingMessages(previous),
      { id: newId, sender: "assistant", text: "", streaming: true, ...(recordParts ? { parts: recordParts } : {}) },
      ...previous.filter((message) => message.sender === "thinking"),
    ]);
  };

  // 本文も下書きも無く、実行記録だけを見せている吹き出しを取り除く。記録だけでは回答にならない。
  // Remove a bubble that shows only the execution record, with neither prose nor a draft; a record alone
  // is not an answer.
  // restoreThinking: 生成がまだ続く場合に立てる。吹き出しと一緒に思考中の表示まで無くなっていたら戻す
  // （下書きが本文に入った時点で思考中の表示は外れているため）。
  // restoreThinking is set while generation continues: if the thinking indicator is gone along with the
  // bubble (a draft joining the bubble had removed it), it is brought back.
  const dropRecordOnlyMessage = (restoreThinking = false) => {
    const streamId = state.streamingMessageId;
    if (!streamId || readShownText() || state.streamingParts?.length) return;
    cancelRender();
    state.streamingMessageId = null;
    state.thinkingKeptBelowMessage = false;
    state.messageHeldByDraft = false;
    const thinkingMessage: UiChatMessage = {
      id: messages.createMessageId("thinking"),
      sender: "thinking",
      text: host.localize("思考中", "Preparing an answer"),
      generationPhase: "generating",
    };
    messages.updateActiveMessages((previous) => {
      const rest = previous.filter((message) => message.id !== streamId);
      const hasThinking = rest.some((message) => message.sender === "thinking");
      return restoreThinking && !hasThinking ? [...rest, thinkingMessage] : rest;
    });
  };

  const ensureStreamingMessage = () => {
    if (state.streamingMessageId) {
      if (state.thinkingKeptBelowMessage) {
        state.thinkingKeptBelowMessage = false;
        messages.updateActiveMessages((previous) => removeThinkingMessages(previous));
      }
      return state.streamingMessageId;
    }
    state.streamingMessageId = messages.createMessageId("assistant-stream");
    const newId = state.streamingMessageId;
    const shownText = readShownText();
    const displayText = getStreamingGenerativeUiDisplayText(shownText);
    const displayParts = composeParts(displayText);
    const generativeUiPending = isGenerativeUiPending(shownText, state.streamingParts);
    const fenceKind = generativeUiFenceKind(shownText);

    messages.updateActiveMessages((previous) => [
      ...removeThinkingMessages(previous),
      {
        id: newId,
        sender: "assistant",
        text: displayText,
        streaming: true,
        generativeUiPending,
        ...(fenceKind ? { generativeUiFenceKind: fenceKind } : {}),
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
    assistantMessageId?: number,
  ) => {
    // 確定テキストを保留中の途中描画で上書きしないようにキャンセルする。
    // Cancel any pending partial render so it cannot overwrite the final text.
    cancelRender();
    const finalDisplayText = finalText || getStreamingGenerativeUiDisplayText(state.streamedText);
    // 終端イベントのパーツは実行記録を含めて確定した全体なので、そのまま使う。
    // The parts of a terminal event are the settled whole, execution record included, so they are used as they are.
    const resolvedParts =
      Array.isArray(parts) && parts.length > 0 ? parts : composeParts(finalDisplayText, true);
    // 実行記録だけ（本文も他のパーツも無い）では回答にならない。記録だけの吹き出しを確定した回答として残さない。
    // An execution record alone, with neither prose nor any other part, is not an answer, so a bubble
    // holding only the record is never left behind as a settled answer.
    const hasAnswerParts =
      Array.isArray(resolvedParts) &&
      resolvedParts.some((part) => !isAnswerTracePart(part) && (part.type !== "text" || Boolean(part.text)));
    const hasParts = Array.isArray(resolvedParts) && resolvedParts.length > 0 && (Boolean(finalDisplayText) || hasAnswerParts);
    const persistAnswer = () => {
      if (persist && finalDisplayText && host.isActive()) {
        storage.persistAssistantAnswer({
          text: finalDisplayText,
          sender: "bot",
          ...(assistantMessageId ? { serverId: assistantMessageId } : {}),
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
            ...(assistantMessageId ? { serverId: assistantMessageId } : {}),
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
    state.thinkingKeptBelowMessage = false;
    if (!finalDisplayText && !hasParts) {
      state.streamingMessageId = null;
      messages.updateActiveMessages((previous) =>
        removeThinkingMessages(previous).filter((message) => message.id !== streamId),
      );
      persistAnswer();
      return;
    }
    messages.updateActiveMessages((previous) =>
      removeThinkingMessages(previous).map((message) =>
        message.id === streamId
          ? {
              ...message,
              text: finalDisplayText || message.text,
              ...(assistantMessageId ? { serverId: assistantMessageId } : {}),
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

  const clearFinalRevealDeadlineTimer = () => {
    if (finalRevealDeadlineTimerId === null) return;
    timers.clearTimeout(finalRevealDeadlineTimerId);
    finalRevealDeadlineTimerId = null;
  };

  const finishPendingFinalization = () => {
    const pending = state.pendingFinalization;
    if (!pending) return;
    state.pendingFinalization = null;
    clearFinalRevealDeadlineTimer();
    finalizeStreamingMessage(pending.finalText, pending.persist, pending.parts, false, pending.assistantMessageId);
    resolveRevealCompletion?.();
    resolveRevealCompletion = null;
  };

  // 下書きだけを本文に持つ吹き出しを片付け、表示ペースを最初に戻す。
  // Clear the bubble whose only prose is a draft and return the display pace to its start.
  const dropDraftMessage = (restoreThinking: boolean) => {
    const streamId = state.streamingMessageId;
    state.messageHeldByDraft = false;
    streamPace.length = 0;
    streamPace.rate = 0;
    streamPace.lastTime = timers.now();
    if (!streamId) return;
    const thinkingMessage: UiChatMessage = {
      id: messages.createMessageId("thinking"),
      sender: "thinking",
      text: host.localize("思考中", "Preparing an answer"),
      generationPhase: "generating",
    };
    // 実行記録を見せている吹き出しは取り除かず、本文だけを空に戻す。表示済みのステップを消さないため。
    // A bubble showing the execution record is kept and only its prose is emptied, so steps already
    // on screen do not disappear.
    const recordParts = state.answerTrace ? withAnswerTracePart([], state.answerTrace) : undefined;
    if (!recordParts) state.streamingMessageId = null;
    state.thinkingKeptBelowMessage = Boolean(recordParts) && restoreThinking;
    messages.updateActiveMessages((previous) => {
      const rest = recordParts
        ? removeThinkingMessages(previous).map((message) =>
            message.id === streamId
              ? { ...message, text: "", parts: recordParts, generativeUiPending: false, generativeUiFenceKind: undefined }
              : message,
          )
        : removeThinkingMessages(previous).filter((message) => message.id !== streamId);
      return restoreThinking ? [...rest, thinkingMessage] : rest;
    });
  };

  // 下書きが捨てられ、確定した本文も続かなかった吹き出しを片付ける。ツール呼び出しに進んだ判断なので、
  // 思考中の表示へ戻す。取り消しの直後に確定した本文が続く場合は、その本文が来るまで吹き出しを残す。
  // Clear a bubble whose draft was discarded with no confirmed text after it. The decision went on to
  // a tool call, so the thinking indicator returns. Right after a discard the bubble stays until the
  // confirmed text that usually follows has arrived.
  const settleEmptiedDraft = () => {
    if (!state.messageHeldByDraft || readShownText()) return false;
    cancelRender();
    dropDraftMessage(true);
    return true;
  };

  // 表示位置を1フレーム分進め、チャンク境界→語境界→引用チップ境界へ丸める。
  // Advance one frame, then round to a chunk, word and citation-chip boundary.
  const resolveDisplayLength = (pacedText: string, frameNow: number) => {
    // done 受信後は締め切りまでに全文へ届く速さで進め、それ以前は通常の上限付き速度で流す。
    // After "done", advance fast enough to reach the full text by the deadline;
    // before it, use the normal capped pace.
    const advancedLength =
      finalRevealDeadline === null
        ? advanceStreamPace(streamPace, pacedText.length, frameNow)
        : advanceStreamPaceToFinish(streamPace, pacedText.length, frameNow, finalRevealDeadline);
    const smoothedLength = clampToCodePointBoundary(pacedText, advancedLength);
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
    if (settleEmptiedDraft()) return;
    const pacedText = getStreamingGenerativeUiDisplayText(readShownText());
    const { displayLength, smoothedLength } = resolveDisplayLength(pacedText, timers.now());
    renderStreamingText(streamId, pacedText.slice(0, displayLength));

    if (smoothedLength < pacedText.length) {
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
    const shownText = readShownText();
    const displayParts = composeParts(displayText);
    const generativeUiPending = isGenerativeUiPending(shownText, state.streamingParts);
    const fenceKind = generativeUiFenceKind(shownText);

    messages.updateActiveMessages((previous) =>
      previous.map((message) =>
        message.id === streamId
          ? {
              ...message,
              text: displayText,
              streaming: true,
              generativeUiPending,
              ...(fenceKind ? { generativeUiFenceKind: fenceKind } : {}),
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
    ensureRecordMessage,
    dropRecordOnlyMessage,
    finalizeStreamingMessage,

    settleEmptiedDraft,

    // 終端イベントで下書きを捨てる。確定した本文が無く下書きだけの吹き出しなら、吹き出しごと取り除く。
    // Drop the draft on a terminal event; a bubble holding only the draft goes with it.
    discardDraft() {
      clearStreamDraft(state);
      if (state.messageHeldByDraft && !state.streamedText) {
        cancelRender();
        dropDraftMessage(false);
        return;
      }
      state.messageHeldByDraft = false;
    },

    updateThinkingStatus(statusText: string, generationPhase: ChatGenerationPhase = "preparing") {
      messages.updateActiveMessages((previous) =>
        previous.map((message) =>
          message.sender === "thinking" ? { ...message, text: statusText, generationPhase } : message,
        ),
      );
    },

    // 最終応答を表示キューへ渡し、未表示分と最後のフェードが完了してから
    // streaming=false にする。高速応答でも末尾が一括表示されなくなる。未表示分は
    // FINAL_REVEAL_WINDOW_MS 内に流し切るため、長い回答でも停止ボタンは長く残らない。
    // Feed the final response through the display queue and only mark it
    // complete after the remaining text and fade have drained. The remainder is
    // flushed within FINAL_REVEAL_WINDOW_MS, so a long answer does not keep the
    // stop button up for long.
    queueFinalization(finalText: string, persist = true, parts?: ChatMessagePart[], assistantMessageId?: number) {
      state.pendingFinalization = { finalText, persist, parts, assistantMessageId };
      if (!revealCompletionPromise) {
        revealCompletionPromise = new Promise<void>((resolve) => {
          resolveRevealCompletion = resolve;
        });
      }
      if (finalRevealDeadline === null) {
        const now = timers.now();
        finalRevealDeadline = now + FINAL_REVEAL_WINDOW_MS;
        // 早送りは経過時間で進めるため、止まっていた間の時間を持ち込まない。
        // The fast-forward follows elapsed time, so do not carry in idle time.
        streamPace.lastTime = now;
        finalRevealDeadlineTimerId = timers.setTimeout(() => {
          finalRevealDeadlineTimerId = null;
          if (!state.pendingFinalization) return;
          cancelRender();
          flushChunkRender();
        }, FINAL_REVEAL_WINDOW_MS);
      }
      scheduleRender();
    },

    // パーツ更新はテキストの書き換えを伴うため、ペーシングせず全文を出す。
    // Parts updates rewrite the text, so show it in full without pacing.
    applyPartsUpdate(displayText: string, parts: ChatMessagePart[] | null) {
      streamPace.length = displayText.length;
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
      clearFinalRevealDeadlineTimer();
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

// 1 本の生成ストリームを最後まで読み切る入口。切断されたら最後に受け取ったイベント ID から再接続して続きを受け取り、完了したら true、中断・失敗・別の生成への置き換えなら false を返す。画面更新と保存はすべて host（注入されたポート）越しに行う。
// Entry point that reads one generation stream to the end. On a drop it reconnects from the last received event id and continues; it resolves true on completion and false on abort, failure, or being superseded. Screen updates and persistence all go through host (the injected ports).
export function consumeGenerationStream(response: Response, host: GenerationStreamHost): Promise<boolean> {
  const timers = host.timers ?? BROWSER_STREAM_TIMERS;
  const reconnectRuntime = host.reconnectRuntime ?? BROWSER_RECONNECT_RUNTIME;
  const { roomId } = host;

  const responseGenerationId = response.headers?.get("X-Chat-Generation-ID") || undefined;
  if (host.generationId && responseGenerationId && host.generationId !== responseGenerationId) {
    void response.body?.cancel().catch(() => {});
    throw new Error(host.localize("別の回答のストリームを受信しました。", "Received a stream for a different answer."));
  }
  let storedGeneration = host.storage.readGenerationState();
  const generationId = responseGenerationId ?? host.generationId ?? storedGeneration?.generationId;
  // 回答が変わったとき、前回の下書きとイベント番号を新しい本文に持ち込まない。
  // Never carry another answer's draft or event cursor into this stream.
  if (generationId && storedGeneration && storedGeneration.generationId !== generationId) {
    storedGeneration = { ...storedGeneration, generationId, lastEventId: 0, streamedText: "", answerTrace: undefined };
    host.lastEventIdByRoom.delete(roomId);
    host.storage.updateGenerationState({ generationId, lastEventId: 0, streamedText: "", answerTrace: undefined });
  }
  if (generationId) {
    host.onGenerationId?.(generationId);
    host.storage.updateGenerationState({ generationId });
  }
  restoreRememberedLastEventId(host, storedGeneration);

  // 等速ペーシングの状態。復元テキストはリプレイせず即時表示する。
  // Constant-pace state. Restored text shows instantly instead of being replayed.
  const restoredText = storedGeneration?.streamedText ?? "";
  const state: StreamSessionState = {
    streamingMessageId: null,
    streamedText: restoredText,
    draftText: "",
    draftDiscardedAt: null,
    messageHeldByDraft: false,
    streamingParts: undefined,
    // 再読み込みの後は、保存しておいた実行記録から再開する（再接続は保存後のイベントしか再送しない）。
    // After a reload, resume from the saved record (a reconnect only replays events after the save).
    answerTrace: storedGeneration?.answerTrace ?? null,
    thinkingKeptBelowMessage: false,
    pendingFinalization: null,
  };

  const renderer = createStreamRenderer(host, state, timers, getStreamingGenerativeUiDisplayText(restoredText).length);
  // 再読み込みの前に見えていた実行記録は、本文がまだ無くてもすぐに戻す。
  // A record that was on screen before a reload comes back at once, even with no prose yet.
  if (!restoredText) renderer.ensureRecordMessage();
  const storedStateSync = createStoredGenerationStateSync(
    host.storage,
    timers,
    () => state.streamedText,
    () => state.answerTrace,
  );

  // TextDecoder は再接続をまたいで共有する（分割されたマルチバイト文字を保つ）。
  // The TextDecoder is shared across reconnects so split multibyte characters survive.
  const textDecoder = new TextDecoder();

  const persistInterruptedStream = (message: string) => {
    renderer.discardDraft();
    renderer.dropRecordOnlyMessage();
    if (state.streamedText.trim()) {
      renderer.finalizeStreamingMessage(
        getStreamingGenerativeUiDisplayText(state.streamedText),
        true,
        // パーツが無いときは undefined のまま渡し、本文と実行記録を最終化側で組み立てさせる。
        // With no parts, pass undefined so finalization assembles the prose and the execution record itself.
        state.streamingParts ? withAnswerTracePart(state.streamingParts, state.answerTrace) : undefined,
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

  // 解釈済みのイベント（action）を、画面更新・保存・完了や失敗の状態（progress）へ反映する。
  // Applies an interpreted event (action) to the screen, to storage, and to the completion/failure state (progress).
  const applyStreamAction = (action: GenerationStreamAction, progress: StreamProgressState) => {
    switch (action.kind) {
      case "ignored":
        return;
      case "chunk":
        renderer.ensureStreamingMessage();
        // 確定した本文は下書きに取って代わる。取り消し済みの下書きは確定分が追いつくまで残し、
        // 取り消しが先に届かなかった下書きは重複させないよう捨てる。
        // Confirmed text supersedes the draft. A discarded draft stays until the confirmed text catches
        // up; a draft whose discard did not arrive first is dropped so it is never duplicated.
        state.messageHeldByDraft = false;
        state.streamedText += action.text;
        if (
          state.draftDiscardedAt === null ||
          state.streamedText.length - state.draftDiscardedAt >= state.draftText.length
        ) {
          clearStreamDraft(state);
        }
        storedStateSync.noteStreamedText();
        renderer.scheduleRender();
        return;
      case "answer_draft": {
        // 吹き出しが無いときも、実行記録だけの吹き出しに入るときも、本文はこの下書きだけになる。
        // Whether there is no bubble yet or only one holding the execution record, this draft is its only prose.
        const createdByDraft = state.streamingMessageId === null || state.thinkingKeptBelowMessage;
        // 初回の描画が下書き全体をペース制御なしで描かないよう、吹き出しを先に作ってから追記する。
        // Create the bubble before appending so its first render does not paint the whole draft unpaced.
        renderer.ensureStreamingMessage();
        if (state.draftDiscardedAt !== null) clearStreamDraft(state);
        state.draftText += action.text;
        if (createdByDraft) state.messageHeldByDraft = true;
        renderer.scheduleRender();
        return;
      }
      case "answer_draft_reset":
        if (action.confirming) {
          // 確定した本文が少しずつ続くので、追いつくまで下書きの残りを表示に残す。
          // The confirmed body follows in pieces, so the rest of the draft stays until it catches up.
          if (state.draftText && state.draftDiscardedAt === null) state.draftDiscardedAt = state.streamedText.length;
        } else {
          // 確定が続かない取り消し（再試行・ツール呼び出し・回復）は、次のイベントを待たずに捨てる。
          // A discard no confirmation follows (retry, tool call, recovery) drops the draft without
          // waiting for the next event.
          clearStreamDraft(state);
        }
        renderer.scheduleRender();
        return;
      case "parts_updated":
        clearStreamDraft(state);
        // 直後に最新テキストで即時描画するため、保留中のチャンク描画は破棄する。
        // Drop the pending chunk render; the immediate update below already
        // carries the latest text.
        renderer.cancelRender();
        renderer.applyPartsUpdate(action.displayText, action.parts);
        return;
      case "answer_trace_updated":
        // 下書きには触れない。同じ内容の再送は描き直さず、本文の描画に任せて次のフレームで載せ替える。
        // 吹き出しがまだ無ければ、実行記録だけの吹き出しを思考中の表示の上に作る。記録が無くなったら、
        // 記録だけの吹き出しは取り除く。
        // The draft is left alone. A resent snapshot with the same content does not redraw; otherwise the next
        // frame swaps it in. With no bubble yet, one holding only the record is created above the thinking
        // indicator; when the record is gone, a bubble holding nothing else is removed.
        if (isSameAnswerTrace(state.answerTrace, action.trace)) return;
        state.answerTrace = action.trace;
        storedStateSync.noteAnswerTrace();
        if (action.trace) renderer.ensureRecordMessage();
        else renderer.dropRecordOnlyMessage(true);
        renderer.scheduleRender();
        return;
      case "thinking_status":
        // 捨てられた下書きの吹き出しが残っていると、進捗の更新先になる思考中の表示が無い。
        // A leftover bubble of a discarded draft would leave no thinking indicator for the update.
        clearStreamDraft(state);
        renderer.settleEmptiedDraft();
        renderer.updateThinkingStatus(action.text, action.phase);
        return;
      case "done":
        progress.completed = true;
        clearStreamDraft(state);
        state.messageHeldByDraft = false;
        host.messages.applyRoomTitle(action.roomTitle);
        renderer.ensureStreamingMessage();
        // 文字送りは UI の代替テキストを除いた本文で行う。保存する text は旧クライアント向けの全文のまま渡す。
        // Pace the reveal with the text that excludes the UI fallback text; the saved text stays the legacy full text.
        state.streamedText = action.displayText;
        renderer.queueFinalization(action.responseText, true, action.parts, action.assistantMessageId);
        host.lastEventIdByRoom.delete(roomId);
        return;
      case "empty_answer":
        // 空の完了は「回答なし」。空の吹き出しを残さずエラーとして扱う。
        // An empty completion means no answer: treat it as an error instead
        // of leaving a blank bubble behind.
        progress.completed = false;
        renderer.discardDraft();
        renderer.dropRecordOnlyMessage();
        host.messages.applyRoomTitle(action.roomTitle);
        progress.streamError = action.message;
        host.lastEventIdByRoom.delete(roomId);
        host.storage.clearGenerationState();
        return;
      case "incomplete":
        progress.completed = true;
        renderer.discardDraft();
        host.messages.applyRoomTitle(action.roomTitle);
        renderer.finalizeStreamingMessage(
          action.finalText,
          Boolean(action.assistantMessageId),
          action.parts,
          true,
          action.assistantMessageId,
        );
        host.messages.appendErrorMessage(action.message);
        host.lastEventIdByRoom.delete(roomId);
        host.storage.clearGenerationState();
        return;
      case "aborted":
        progress.completed = true;
        renderer.discardDraft();
        renderer.finalizeStreamingMessage(
          action.finalText,
          Boolean(action.assistantMessageId),
          action.parts,
          false,
          action.assistantMessageId,
        );
        host.storage.clearGenerationState();
        return;
      case "error":
        renderer.discardDraft();
        renderer.dropRecordOnlyMessage();
        progress.streamError = action.message;
        return;
    }
  };

  // 再接続の成否判定に使う、これまでに反映した新しいイベントの数。再送された
  // 既読イベントと、何も変えないイベントは数えない。
  // Count of new events applied so far, used to judge whether a reconnect made
  // progress. Replayed events and events that change nothing are not counted.
  let appliedEventCount = 0;
  let highestDraftEventId = 0;

  // SSE の 1 ブロックを解釈して反映する。受信済みの ID の再送は捨てる。下書きは再開位置や保存に含めず、再接続で先頭から組み立て直す。
  // Interprets and applies one SSE block. A resent event with an already-seen id is dropped. Drafts are excluded from the resume position and storage and are rebuilt from the start on reconnect.
  const processBlock = (block: string, progress: StreamProgressState) => {
    const parsed = parseStreamEventBlock(block);
    if (!parsed) return;
    if (!host.isActive()) return;

    const action = interpretGenerationStreamEvent(parsed, { streamedText: state.streamedText, localize: host.localize });
    // 下書きは復元データにも、ルームをまたぐ再開位置にも残さない。どちらも下書きのイベントでは進めず、
    // 再接続は最後の非下書きイベントの次から再生して、下書きを先頭から組み立て直す。進めると、
    // 再読み込みやルーム切り替えの後に下書きの途中から再開し、先頭の欠けた下書きが見える。
    // 受信済みのイベントの再送は、記録しなくても捨てる。
    // A draft is kept out of both the stored recovery data and the per-room resume position. Neither
    // advances on a draft event, so a reconnect replays from just after the last non-draft event and
    // rebuilds the draft from its start; advancing them would resume mid-draft after a reload or a
    // room switch and show a draft missing its head. A resent event is still dropped, unrecorded.
    let countsAsProgress = action.kind !== "ignored";
    if (action.kind === "answer_draft") {
      const lastEventId = host.lastEventIdByRoom.get(roomId) ?? 0;
      if (typeof parsed.id === "number" && parsed.id > 0) {
        if (parsed.id <= lastEventId) return;
        // 再接続で再生し直した下書きは、再接続の成否を測る進捗に数えない。
        // A draft replayed after a reconnect does not count as progress for judging the reconnect.
        countsAsProgress = parsed.id > highestDraftEventId;
        highestDraftEventId = Math.max(highestDraftEventId, parsed.id);
      }
    } else {
      if (!rememberStreamEventId(host.lastEventIdByRoom, roomId, parsed.id)) return;
      if (typeof parsed.id === "number" && parsed.id > 0) {
        storedStateSync.noteLastEventId(parsed.id);
      }
    }
    if (countsAsProgress) appliedEventCount += 1;
    applyStreamAction(action, progress);
  };

  // 1 回の接続分の本文を読み切り、完了・切断・中止・別生成への置き換え・エラーのどれで終わったかを返す。
  // Reads one connection's body to the end and reports how it ended: completed, interrupted, aborted, superseded, or error.
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
      // 回線の切り替えは通常 TypeError として現れるが、ブラウザによっては既存の SSE 応答を破棄するときに AbortError を使う。
      // どちらもユーザーが取り消したのではなく接続が切れただけなので、失敗扱いにせず最後のイベント ID から再開する。
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
        // 読み取りの後始末の失敗は無視する。
        // no-op
      });
    }

    if (progress.streamError) {
      return { status: "error", message: progress.streamError };
    }

    return progress.completed ? "completed" : "interrupted";
  };

  // 最後のイベント ID を付けてストリームを開き直す。再開位置が無い・別の生成だった・復旧不能なステータスなら "unavailable"、一時的な失敗なら null を返す。
  // Reopens the stream with the last event id. Returns "unavailable" when there is no resume point, the stream belongs to another generation, or the status is unrecoverable, and null for a transient failure.
  const openReconnectStream = async (): Promise<Response | "unavailable" | null> => {
    const lastEventId = host.lastEventIdByRoom.get(roomId);
    // 再開位置が無いまま切れた（1イベントも届かなかった）場合は、何度試しても
    // サーバーへ「どこから続けるか」を伝えられない。待つだけ無駄なので即座に諦める。
    // Dropping before a single event id arrived leaves no resume point, so no
    // number of retries can tell the server where to continue. Give up at once.
    if (typeof lastEventId !== "number" || lastEventId <= 0) return "unavailable";

    try {
      const reconnectResponse = await host.openStream(lastEventId, generationId);
      const reconnectGenerationId = reconnectResponse.headers?.get("X-Chat-Generation-ID");
      if (generationId && reconnectGenerationId && reconnectGenerationId !== generationId) {
        await reconnectResponse.body?.cancel();
        return "unavailable";
      }
      if (!reconnectResponse.ok) {
        // 使わない本文は破棄する。放置すると接続が解放されない。
        // Discard the unused body; leaving it open leaks the connection.
        try {
          await reconnectResponse.body?.cancel();
        } catch {
          // 本文の破棄に失敗しても何もしない。
          // no-op
        }
        return isUnrecoverableStreamStatus(reconnectResponse.status) ? "unavailable" : null;
      }
      return reconnectResponse;
    } catch {
      return null;
    }
  };

  // 再開できないと確定したとき、ここまでに届いた回答を保存してエラーとして終える。
  // When resuming is ruled out, saves what has arrived so far and ends with an error.
  const persistUnresumableStream = () => {
    persistInterruptedStream(
      state.streamedText
        ? host.localize(
            "ストリームを再開できませんでした。ここまでの応答を保存しました。",
            "The stream could not be resumed. The response received so far was saved.",
          )
        : host.localize("ストリームを再開できませんでした。", "The stream could not be resumed."),
    );
  };

  // 読み取り → 再接続待ち（バックオフ）→ 再接続を繰り返すループ。進捗の無い再接続が上限（MAX_GENERATION_STREAM_RECONNECT_ATTEMPTS）に達したら諦める。
  // The loop of read, backoff wait, and reconnect. It gives up once reconnects without progress reach the cap (MAX_GENERATION_STREAM_RECONNECT_ATTEMPTS).
  const runStreamWithReconnects = async (initialResponse: Response): Promise<boolean> => {
    let activeResponse = initialResponse;
    let reconnectAttempt = 0;

    while (host.isActive()) {
      const eventsBeforeRead = appliedEventCount;
      const result = await readStreamResponse(activeResponse);
      if (!host.isActive()) return false;
      // 新しいイベントを受け取れた応答だけを再接続の成功と数え、連続で進捗が
      // 無かった回数を数え直す。
      // Only a response that delivered a new event counts as a successful
      // reconnect; restart the count of consecutive attempts without progress.
      if (appliedEventCount > eventsBeforeRead) reconnectAttempt = 0;

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

      // 200 で開いたのに何も届かず閉じる再接続が続いても、上限で必ず終わらせる。
      // Even reconnects that open with a 200 but close empty must end at the cap.
      if (reconnectAttempt >= MAX_GENERATION_STREAM_RECONNECT_ATTEMPTS) {
        persistUnresumableStream();
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
        persistUnresumableStream();
        return false;
      }
      if (!reconnectResponse) {
        // Wi-Fi が切れると、ブラウザがオンラインと報告したあとも最初の数回の再接続が失敗することがある。
        // ローカルの進捗は保ったまま再試行を続けるが、試行が尽きたら必ず止めて、空回りさせずに見える結果で終える。
        // A lost Wi-Fi connection can make the first few reconnects fail
        // even after the browser reports online. Keep the local progress
        // and continue retrying, but stop once the attempts run out so the
        // turn always ends with a visible result instead of spinning forever.
        if (reconnectAttempt >= MAX_GENERATION_STREAM_RECONNECT_ATTEMPTS) {
          persistUnresumableStream();
          return false;
        }
        continue;
      }
      activeResponse = reconnectResponse;
      // 再接続は最後の非下書きイベントの次から再生するので、下書きは再生分から組み立て直す。
      // The reconnect replays from after the last non-draft event, so the draft is rebuilt from the replay.
      clearStreamDraft(state);
      renderer.scheduleRender();
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
