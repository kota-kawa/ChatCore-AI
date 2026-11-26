import type { GenerationStreamReconnectRuntime } from "./generation_stream_reconnect";
import type {
  StoredGenerationState,
  StoredHistoryEntry,
  UiChatMessage,
} from "./types";
import type { StreamLocalize } from "./generation_stream_events";

export type GenerationStreamTimers = {
  now: () => number;
  setTimeout: (handler: () => void, ms: number) => number;
  clearTimeout: (timerId: number) => void;
  requestAnimationFrame: (handler: () => void) => number;
  cancelAnimationFrame: (handle: number) => void;
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
  // 終端イベント後に返された候補から、保存済みの自動タイトルを非同期で探す。
  // Look up a persisted auto-title asynchronously after a terminal event supplies its initial-title candidates.
  startDeferredRoomTitlePolling?: (initialTitleCandidates: readonly string[]) => void;
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
