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

// fetch はヘッダーが届いた時点で解決するため、本文の読み取りはタイムアウトの外に
// 出てしまう。ヘッダーだけ返して本文で止まるサーバーやプロキシに対しては、
// res.json() / res.text() が無制限に待つことになる。
// そこで本文を素通しするストリームで包み、読み切る（またはキャンセルされる）まで
// タイムアウトと呼び出し側の中断を生かしたままにする。バッファリングはしないので、
// 逐次読み出し（SSE など）の挙動は変わらない。
//
// fetch settles as soon as the headers arrive, so reading the body used to fall
// outside the timeout: against a server that returns headers and then stalls,
// res.json() / res.text() waited forever. Wrap the body in a pass-through stream
// so the deadline (and the caller's abort) stays armed until the body is fully
// read or cancelled. Nothing is buffered, so incremental readers are unaffected.
function withBodyDeadline(response: Response, release: () => void): Response {
  const source = response.body;
  // 本文を持たない応答（204 など）や、Response として作り直せない応答はそのまま返す。
  // Bodyless responses (204 and friends) and ones we cannot rebuild pass through.
  if (!source || response.status < 200) {
    release();
    return response;
  }

  const reader = source.getReader();
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (done) {
          release();
          controller.close();
          return;
        }
        controller.enqueue(value);
      } catch (error) {
        release();
        controller.error(error);
      }
    },
    cancel(reason) {
      release();
      return reader.cancel(reason);
    },
  });

  const wrapped = new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
  // Response のコンストラクタでは復元できない情報（リダイレクト先など）を引き継ぐ。
  // Carry over the fields the Response constructor cannot reproduce (a caller may
  // follow response.url after a redirect).
  for (const key of ["url", "redirected", "type"] as const) {
    Object.defineProperty(wrapped, key, { get: () => response[key], configurable: true });
  }
  return wrapped;
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
    // 本文を呼び出し側へ引き渡した後は、finally での即時クリアではなく
    // withBodyDeadline 側の release() にタイムアウト解除を委ねる。
    // Once the body is handed off to the caller, timeout teardown is deferred
    // to withBodyDeadline's release() instead of the immediate finally below.
    let handedOffToBody = false;
    const timeoutId =
      timeoutMs > 0
        ? setTimeout(() => {
            timedOut = true;
            controller.abort(new DOMException("Request timed out", "TimeoutError"));
          }, timeoutMs)
        : null;
    const cleanupAttempt = () => {
      if (timeoutId !== null) clearTimeout(timeoutId);
      callerSignal?.removeEventListener("abort", onCallerAbort);
    };

    try {
      const response = await fetch(input, { ...init, signal: controller.signal });

      // 5xx かつリトライ可能なら再試行、それ以外（2xx/3xx/4xx）はそのまま返す。
      // Retry on 5xx when allowed; otherwise return the response as-is (2xx/3xx/4xx).
      if (isRetryableStatus(response.status) && attempt < maxRetries) {
        lastError = new Error(`Server responded with status ${response.status}`);
      } else {
        // ここで cleanupAttempt() を即実行すると、本文の読み取り中はタイムアウトも
        // 呼び出し側の中断も効かなくなる（fetch はヘッダー到達で解決するため）。
        // withBodyDeadline が本文を読み切る／キャンセルされるまで持ち越す。
        // Running cleanupAttempt() here would leave the body read unguarded,
        // since fetch settles as soon as headers arrive. Defer it until
        // withBodyDeadline finishes or cancels the body.
        handedOffToBody = true;
        // 呼び出し側がステータスだけ見て本文を一度も読まない／キャンセルしない
        // 場合、withBodyDeadline の pull() は本文を読み切るまで release() を
        // 呼ばない（ReadableStream は内部キューが埋まると自動では pull() を
        // 再実行しない）。それだけに頼ると、タイムアウトタイマーと中断リスナーが
        // 残り続けてしまう。内部 AbortController の中断（タイムアウト発火／
        // 呼び出し側の中断の転送）にも後始末を結び付け、本文が読まれなくても
        // 高々 timeoutMs で片付くようにする。
        // If the caller only checks the status and never reads or cancels the
        // body, withBodyDeadline's pull() never calls release() (a
        // ReadableStream does not auto-repull once its internal queue is
        // full). Relying on that alone would leave the timeout timer and the
        // abort listener dangling. Also tie cleanup to the internal
        // AbortController firing (timeout or a forwarded caller abort), so an
        // unread body is still cleaned up within at most timeoutMs.
        controller.signal.addEventListener("abort", cleanupAttempt, { once: true });
        return withBodyDeadline(response, cleanupAttempt);
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
      if (!handedOffToBody) cleanupAttempt();
    }

    // ここに到達したのはリトライ可能な失敗。次の試行まで待機する。
    // Reaching here means a retryable failure; wait before the next attempt.
    if (attempt < maxRetries) {
      await delay(computeBackoffDelay(attempt, baseDelayMs, maxDelayMs), callerSignal);
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Request failed after retries");
}
