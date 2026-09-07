// SSE は回線切替時にブラウザから明示的なエラーとして通知されないことがある。
// 最初はすぐ再接続し、以後は上限付きバックオフでサーバー側で継続中の生成へ戻る。
// An SSE connection may end without a useful browser error during a network
// handoff. Reconnect immediately once, then use capped backoff while the
// generation continues on the server.

export const GENERATION_STREAM_RECONNECT_DELAYS_MS = [0, 500, 1_000, 2_000, 4_000, 8_000, 15_000];

// 待機に必要な最小限のブラウザ機能。テストでは仮想タイマーを差し込む。
// The minimum browser surface the waits need; tests inject virtual timers.
export type GenerationStreamReconnectRuntime = {
  setTimeout: (handler: () => void, ms: number) => number;
  clearTimeout: (timerId: number) => void;
  // navigator.onLine === false と同義（SSR では常に false）。
  // Equivalent to navigator.onLine === false (always false during SSR).
  isOffline: () => boolean;
  addOnlineListener: (listener: () => void) => void;
  removeOnlineListener: (listener: () => void) => void;
};

export const BROWSER_RECONNECT_RUNTIME: GenerationStreamReconnectRuntime = {
  setTimeout: (handler, ms) => window.setTimeout(handler, ms),
  clearTimeout: (timerId) => window.clearTimeout(timerId),
  isOffline: () => typeof window !== "undefined" && navigator.onLine === false,
  addOnlineListener: (listener) => window.addEventListener("online", listener, { once: true }),
  removeOnlineListener: (listener) => window.removeEventListener("online", listener),
};

export function createAbortError(signal: AbortSignal) {
  return signal.reason instanceof Error ? signal.reason : new DOMException("Aborted", "AbortError");
}

// 4xx は「そのリクエスト自体が受け付けられなかった」ため、再接続しても復旧しない。
// A 4xx means the request itself was not accepted, so retrying cannot recover
// it (408 and 429 are transient and stay retryable).
export function isUnrecoverableStreamStatus(status: number): boolean {
  return status >= 400 && status < 500 && status !== 408 && status !== 429;
}

export function waitForDuration(
  ms: number,
  signal: AbortSignal,
  runtime: GenerationStreamReconnectRuntime = BROWSER_RECONNECT_RUNTIME,
) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(createAbortError(signal));
      return;
    }

    const timerId = runtime.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      runtime.clearTimeout(timerId);
      reject(createAbortError(signal));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function waitUntilOnline(
  signal: AbortSignal,
  runtime: GenerationStreamReconnectRuntime = BROWSER_RECONNECT_RUNTIME,
) {
  if (!runtime.isOffline()) {
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
      runtime.removeOnlineListener(onOnline);
      signal.removeEventListener("abort", onAbort);
    };

    runtime.addOnlineListener(onOnline);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export async function waitForGenerationStreamReconnect(
  attempt: number,
  signal: AbortSignal,
  runtime: GenerationStreamReconnectRuntime = BROWSER_RECONNECT_RUNTIME,
) {
  await waitUntilOnline(signal, runtime);
  const delayIndex = Math.min(attempt, GENERATION_STREAM_RECONNECT_DELAYS_MS.length - 1);
  await waitForDuration(GENERATION_STREAM_RECONNECT_DELAYS_MS[delayIndex], signal, runtime);
}
