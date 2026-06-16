// 遅い・不安定なネットワークでもユーザーが体感する待ち時間を抑えるための fetch ラッパー。
// A fetch wrapper that keeps perceived latency low on slow or flaky networks.
//
// 標準の fetch は (1) 応答が来るまで無限に待ち続け、(2) 一時的な切断で即座に失敗する。
// このラッパーは GET/HEAD のような冪等リクエストに対して以下を提供する:
//   - タイムアウト: 一定時間で中断し、ハングしたままになるのを防ぐ。
//   - リトライ: ネットワークエラー・タイムアウト・5xx を指数バックオフで再試行する。
// UI は一切変えず、データ取得の粘り強さだけを高める。
//
// The standard fetch (1) waits forever for a response and (2) fails instantly on a
// transient hiccup. For idempotent requests (GET/HEAD) this wrapper adds:
//   - Timeout: abort after a bounded time so requests never hang indefinitely.
//   - Retry: re-attempt on network errors, timeouts, and 5xx with exponential backoff.
// It changes no UI; it only makes data fetching more resilient.

export type ResilientFetchOptions = {
  // リクエストごとのタイムアウト（ミリ秒）。0 以下で無効化。
  // Per-attempt timeout in milliseconds. Disabled when <= 0.
  timeoutMs?: number;
  // 冪等リクエストの最大リトライ回数（初回を除く）。
  // Maximum number of retries (excluding the first attempt) for idempotent requests.
  retries?: number;
  // バックオフの基準遅延（ミリ秒）。実際の遅延は基準 * 2^attempt + ジッター。
  // Base backoff delay in milliseconds. Actual delay is base * 2^attempt + jitter.
  retryBaseDelayMs?: number;
  // バックオフ遅延の上限（ミリ秒）。
  // Upper bound for the backoff delay in milliseconds.
  retryMaxDelayMs?: number;
};

const DEFAULT_TIMEOUT_MS = 15_000;
const DEFAULT_RETRIES = 2;
const DEFAULT_RETRY_BASE_DELAY_MS = 400;
const DEFAULT_RETRY_MAX_DELAY_MS = 4_000;

// GET / HEAD のみリトライ対象とする（副作用がなく再送が安全なため）。
// Only GET/HEAD are retried (no side effects, so re-sending is safe).
const RETRYABLE_METHODS = new Set(["GET", "HEAD"]);

function resolveMethod(input: RequestInfo | URL, init?: RequestInit): string {
  if (init?.method) return init.method.toUpperCase();
  if (typeof Request !== "undefined" && input instanceof Request) return input.method.toUpperCase();
  return "GET";
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason instanceof Error ? signal.reason : new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason instanceof Error ? signal.reason : new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function computeBackoffDelay(attempt: number, baseMs: number, maxMs: number): number {
  const exponential = baseMs * 2 ** attempt;
  // フルジッターでサーバーへの同時再送（サンダリングハード）を緩和する。
  // Full jitter to avoid synchronized retries (thundering herd) against the server.
  const jittered = Math.random() * exponential;
  return Math.min(maxMs, Math.round(jittered));
}

// 5xx はサーバー側の一時的な不調の可能性が高いためリトライ、4xx はしない。
// 5xx is likely a transient server issue (retry); 4xx is a client error (do not retry).
function isRetryableStatus(status: number): boolean {
  return status >= 500 && status <= 599;
}

// fetch のネットワークエラー（TypeError）かどうかを判定する。
// Detect a fetch network error (surfaced as a TypeError).
function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException ? error.name === "AbortError" : (error as { name?: string })?.name === "AbortError";
}

/**
 * タイムアウトとリトライを備えた fetch。冪等(GET/HEAD)リクエストのみ自動リトライする。
 * A fetch with timeout and retry. Only idempotent (GET/HEAD) requests are retried automatically.
 *
 * 呼び出し側が init.signal を渡した場合はそれを尊重し、その中断はリトライ対象外として即座に伝播する。
 * If the caller passes init.signal, it is honored: a caller-driven abort is propagated immediately
 * and is never treated as a retryable failure.
 */
export async function resilientFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
  options?: ResilientFetchOptions,
): Promise<Response> {
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const method = resolveMethod(input, init);
  const canRetry = RETRYABLE_METHODS.has(method);
  const maxRetries = canRetry ? options?.retries ?? DEFAULT_RETRIES : 0;
  const baseDelayMs = options?.retryBaseDelayMs ?? DEFAULT_RETRY_BASE_DELAY_MS;
  const maxDelayMs = options?.retryMaxDelayMs ?? DEFAULT_RETRY_MAX_DELAY_MS;

  const callerSignal = init?.signal ?? undefined;

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    // 呼び出し側が既に中断していれば、無駄な試行をせず即座に中断を伝える。
    // If the caller already aborted, propagate immediately without a wasted attempt.
    if (callerSignal?.aborted) {
      throw callerSignal.reason instanceof Error ? callerSignal.reason : new DOMException("Aborted", "AbortError");
    }

    const controller = new AbortController();
    // 呼び出し側の中断をこの試行に伝播させる。
    // Forward the caller's abort into this attempt.
    const onCallerAbort = () => controller.abort(callerSignal?.reason);
    callerSignal?.addEventListener("abort", onCallerAbort, { once: true });

    let timedOut = false;
    const timeoutId =
      timeoutMs > 0
        ? setTimeout(() => {
            timedOut = true;
            controller.abort(new DOMException("Request timed out", "TimeoutError"));
          }, timeoutMs)
        : null;

    try {
      const response = await fetch(input, { ...init, signal: controller.signal });

      // 5xx かつリトライ可能なら再試行、それ以外（2xx/3xx/4xx）はそのまま返す。
      // Retry on 5xx when allowed; otherwise return the response as-is (2xx/3xx/4xx).
      if (isRetryableStatus(response.status) && attempt < maxRetries) {
        lastError = new Error(`Server responded with status ${response.status}`);
      } else {
        return response;
      }
    } catch (error) {
      // タイムアウトによる中断はリトライ対象。呼び出し側による中断はそのまま伝播する。
      // Abort due to timeout is retryable; an abort driven by the caller is propagated as-is.
      if (isAbortError(error) && !timedOut) {
        throw error;
      }
      if (!timedOut && !isNetworkError(error)) {
        // 想定外のエラーはリトライせずに投げる。
        // Unexpected errors are thrown without retrying.
        throw error;
      }
      lastError = error;
    } finally {
      if (timeoutId !== null) clearTimeout(timeoutId);
      callerSignal?.removeEventListener("abort", onCallerAbort);
    }

    // ここに到達したのはリトライ可能な失敗。次の試行まで待機する。
    // Reaching here means a retryable failure; wait before the next attempt.
    if (attempt < maxRetries) {
      await delay(computeBackoffDelay(attempt, baseDelayMs, maxDelayMs), callerSignal);
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Request failed after retries");
}
