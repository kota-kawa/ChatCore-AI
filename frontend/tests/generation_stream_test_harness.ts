// 生成ストリームのロジックテスト用の仮想環境。ブラウザ API（rAF・タイマー・
// localStorage）を持たない Node 上で、フレームと時間の進み方をテストが完全に
// 制御できるようにする。
// Virtual environment for the generation-stream logic tests. Node has no
// browser APIs (rAF, timers, localStorage), so the tests drive frames and time
// themselves and observe every port the runtime writes through.

import type {
  GenerationStreamHost,
  GenerationStreamTimers,
} from "../lib/chat_page/generation_stream_consumer";
import type { GenerationStreamReconnectRuntime } from "../lib/chat_page/generation_stream_reconnect";
import type { StoredGenerationState, StoredHistoryEntry, UiChatMessage } from "../lib/chat_page/types";

type ScheduledTimer = {
  dueAt: number;
  handler: () => void;
};

export type FakeClock = {
  timers: GenerationStreamTimers;
  reconnectRuntime: GenerationStreamReconnectRuntime;
  now: () => number;
  // 予約済みフレームを1巡だけ実行する（その中で予約された分は次回に回す）。
  // Run exactly one generation of queued frames; frames they queue wait.
  runFrames: () => number;
  // 時間を進め、期限の来たタイマーを発火させる。
  // Advance time and fire every timer that came due.
  advance: (ms: number) => void;
  setOffline: (offline: boolean) => void;
  goOnline: () => void;
  // 記録した setTimeout の待ち時間（再接続バックオフの検証用）。
  // Recorded setTimeout delays, used to assert the reconnect backoff.
  recordedDelays: number[];
};

export function createFakeClock(): FakeClock {
  let now = 0;
  let nextHandle = 1;
  let offline = false;
  const timeouts = new Map<number, ScheduledTimer>();
  const frames = new Map<number, () => void>();
  const onlineListeners = new Set<() => void>();
  const recordedDelays: number[] = [];

  const schedule = (handler: () => void, ms: number) => {
    const handle = nextHandle++;
    recordedDelays.push(ms);
    timeouts.set(handle, { dueAt: now + ms, handler });
    return handle;
  };

  const timers: GenerationStreamTimers = {
    now: () => now,
    setTimeout: schedule,
    clearTimeout: (handle) => {
      timeouts.delete(handle);
    },
    requestAnimationFrame: (handler) => {
      const handle = nextHandle++;
      frames.set(handle, handler);
      return handle;
    },
    cancelAnimationFrame: (handle) => {
      frames.delete(handle);
    },
  };

  const reconnectRuntime: GenerationStreamReconnectRuntime = {
    setTimeout: schedule,
    clearTimeout: (handle) => {
      timeouts.delete(handle);
    },
    isOffline: () => offline,
    addOnlineListener: (listener) => {
      onlineListeners.add(listener);
    },
    removeOnlineListener: (listener) => {
      onlineListeners.delete(listener);
    },
  };

  return {
    timers,
    reconnectRuntime,
    now: () => now,
    recordedDelays,
    runFrames() {
      const pending = [...frames.entries()];
      frames.clear();
      pending.forEach(([, handler]) => handler());
      return pending.length;
    },
    advance(ms: number) {
      now += ms;
      [...timeouts.entries()]
        .filter(([, timer]) => timer.dueAt <= now)
        .sort((a, b) => a[1].dueAt - b[1].dueAt)
        .forEach(([handle, timer]) => {
          timeouts.delete(handle);
          timer.handler();
        });
    },
    setOffline(next: boolean) {
      offline = next;
    },
    goOnline() {
      offline = false;
      const listeners = [...onlineListeners];
      onlineListeners.clear();
      listeners.forEach((listener) => listener());
    },
  };
}

export type StreamHostRecorder = {
  host: GenerationStreamHost;
  messages: () => UiChatMessage[];
  errors: () => string[];
  roomTitles: () => unknown[];
  persistedAnswers: () => StoredHistoryEntry[];
  unansweredFailures: () => string[];
  generationStateClears: () => number;
  storedGeneration: () => StoredGenerationState | null;
  lastEventIds: Map<string, number>;
  setActive: (active: boolean) => void;
  abortController: AbortController;
};

export type StreamHostOptions = {
  roomId?: string;
  clock: FakeClock;
  storedGeneration?: StoredGenerationState | null;
  // 再接続要求ごとに返すレスポンス。足りなければ最後の値を使い続ける。
  // Responses returned per reconnect request; the last one repeats.
  openStream?: (lastEventId: number) => Promise<Response>;
  withUnansweredFailureHandler?: boolean;
};

export function createStreamHostRecorder(options: StreamHostOptions): StreamHostRecorder {
  const roomId = options.roomId ?? "room-1";
  const abortController = new AbortController();
  const lastEventIds = new Map<string, number>();

  let active = true;
  let messages: UiChatMessage[] = [];
  let messageSeq = 0;
  let storedGeneration: StoredGenerationState | null = options.storedGeneration ?? null;
  let generationStateClears = 0;

  const errors: string[] = [];
  const roomTitles: unknown[] = [];
  const persistedAnswers: StoredHistoryEntry[] = [];
  const unansweredFailures: string[] = [];

  const host: GenerationStreamHost = {
    roomId,
    abortSignal: abortController.signal,
    isActive: () => active,
    lastEventIdByRoom: lastEventIds,
    localize: (ja) => ja,
    timers: options.clock.timers,
    reconnectRuntime: options.clock.reconnectRuntime,
    messages: {
      updateActiveMessages: (updater) => {
        if (!active) return;
        messages = updater(messages);
      },
      createMessageId: (prefix) => {
        messageSeq += 1;
        return `${prefix}-${messageSeq}`;
      },
      appendErrorMessage: (message) => {
        errors.push(message);
        messageSeq += 1;
        messages = [
          ...messages.filter((entry) => entry.sender !== "thinking"),
          { id: `assistant-error-${messageSeq}`, sender: "assistant", text: `エラー: ${message}`, error: true },
        ];
      },
      applyRoomTitle: (title) => {
        roomTitles.push(title);
      },
    },
    storage: {
      readGenerationState: () => storedGeneration,
      updateGenerationState: (updates) => {
        if (!storedGeneration) return;
        storedGeneration = { ...storedGeneration, ...updates };
      },
      clearGenerationState: () => {
        generationStateClears += 1;
        storedGeneration = null;
      },
      persistAssistantAnswer: (entry) => {
        persistedAnswers.push(entry);
      },
    },
    openStream:
      options.openStream
      ?? (() => Promise.reject(new Error("openStream was not expected in this test"))),
    ...(options.withUnansweredFailureHandler
      ? {
          onUnansweredFailure: (message: string) => {
            unansweredFailures.push(message);
          },
        }
      : {}),
  };

  return {
    host,
    messages: () => messages,
    errors: () => errors,
    roomTitles: () => roomTitles,
    persistedAnswers: () => persistedAnswers,
    unansweredFailures: () => unansweredFailures,
    generationStateClears: () => generationStateClears,
    storedGeneration: () => storedGeneration,
    lastEventIds,
    setActive: (next) => {
      active = next;
    },
    abortController,
  };
}

const encoder = new TextEncoder();

export type ScriptedStream = {
  response: Response;
  // 読み出し済みのブロック数 / how many scripted reads were consumed
  readCount: () => number;
};

type ScriptedStep = string | { error: unknown };

// SSE ブロック列（または途中で投げるエラー）を1本のレスポンスとして再現する。
// Replays a list of SSE blocks (or a mid-stream throw) as one response.
export function createScriptedStream(steps: ScriptedStep[], options?: { bodyless?: boolean }): ScriptedStream {
  let index = 0;

  const reader = {
    read: async () => {
      if (index >= steps.length) return { value: undefined, done: true };
      const step = steps[index];
      index += 1;
      if (typeof step !== "string") throw step.error;
      return { value: encoder.encode(step), done: false };
    },
    cancel: async () => undefined,
  };

  const response = {
    ok: true,
    status: 200,
    headers: { get: () => "text/event-stream" },
    body: options?.bodyless ? null : { getReader: () => reader },
  } as unknown as Response;

  return { response, readCount: () => index };
}

export function sseBlock(id: number | null, event: string, data: unknown) {
  const idLine = id === null ? "" : `id: ${id}\n`;
  return `${idLine}event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

export function rawSseBlock(id: number | null, event: string, rawData: string) {
  const idLine = id === null ? "" : `id: ${id}\n`;
  return `${idLine}event: ${event}\ndata: ${rawData}\n\n`;
}

// マイクロタスクを完全に排出する（reader.read() の解決を待つため）。
// Fully drain the microtask queue so reader.read() settles.
export function flushMicrotasks() {
  return new Promise<void>((resolve) => setImmediate(resolve));
}

// 仮想フレームと仮想時間を進めながら promise の決着を待つ。
// Drive virtual frames and virtual time until the promise settles.
export async function settleStream<T>(promise: Promise<T>, clock: FakeClock, maxSteps = 400): Promise<T> {
  let settled = false;
  const tracked = promise.then(
    (value) => {
      settled = true;
      return value;
    },
    (error) => {
      settled = true;
      throw error;
    },
  );
  // 例外は最後にまとめて投げ直すので、ここでは無視して監視だけ続ける。
  // The rejection is rethrown at the end; here it is only observed.
  tracked.catch(() => undefined);

  for (let step = 0; step < maxSteps && !settled; step += 1) {
    await flushMicrotasks();
    if (settled) break;
    clock.runFrames();
    clock.advance(60);
    await flushMicrotasks();
  }

  return tracked;
}
