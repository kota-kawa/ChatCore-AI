// SSE は回線切替時にブラウザから明示的なエラーとして通知されないことがある。
// 最初はすぐ再接続し、以後は上限付きバックオフでサーバー側で継続中の生成へ戻る。
// An SSE connection may end without a useful browser error during a network
// handoff. Reconnect immediately once, then use capped backoff while the
// generation continues on the server.

// 再接続の待ち時間（ミリ秒）。試行回数に応じて 0 から 15 秒まで伸ばし、以降は最後の値を使い続ける。
// Reconnect wait times (ms), growing from 0 to 15 s with the attempt number; the last value is reused afterwards.
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

// 中止シグナルの reason があればそれを、無ければ AbortError を返す。
// Returns the abort signal's reason when present, otherwise an AbortError.
export function createAbortError(signal: AbortSignal) {
  return signal.reason instanceof Error ? signal.reason : new DOMException("Aborted", "AbortError");
}

// 4xx は「そのリクエスト自体が受け付けられなかった」ため、再接続しても復旧しない。
// A 4xx means the request itself was not accepted, so retrying cannot recover
// it (408 and 429 are transient and stay retryable).
export function isUnrecoverableStreamStatus(status: number): boolean {
  return status >= 400 && status < 500 && status !== 408 && status !== 429;
}

// 指定時間待つ。途中で signal が中止されたらタイマーを解除して AbortError で reject する。
// Waits for the given time; if the signal aborts meanwhile, clears the timer and rejects with an AbortError.
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

// オフラインの間は online イベントまで待つ（オンラインなら即解決）。signal が中止されたら reject する。
// While offline, waits for the online event (resolves at once when online); rejects if the signal aborts.
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

// 再接続の前に、オンラインになるのを待ち、さらに試行回数に応じたバックオフ時間だけ待つ。
// Before reconnecting, waits until online and then for the backoff time matching the attempt number.
export async function waitForGenerationStreamReconnect(
  attempt: number,
  signal: AbortSignal,
  runtime: GenerationStreamReconnectRuntime = BROWSER_RECONNECT_RUNTIME,
) {
  await waitUntilOnline(signal, runtime);
  const delayIndex = Math.min(attempt, GENERATION_STREAM_RECONNECT_DELAYS_MS.length - 1);
  await waitForDuration(GENERATION_STREAM_RECONNECT_DELAYS_MS[delayIndex], signal, runtime);
}
