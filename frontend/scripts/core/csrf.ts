const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const originalFetch = window.fetch.bind(window);
let csrfTokenPromise: Promise<string> | null = null;

const isSameOrigin = (target: string): boolean => {
  try {
    const url = new URL(target, window.location.origin);
    return url.origin === window.location.origin;
  } catch {
    return true;
  }
};

const getCsrfToken = async (): Promise<string> => {
  if (!csrfTokenPromise) {
    csrfTokenPromise = originalFetch("/api/csrf-token", {
      method: "GET",
      credentials: "same-origin"
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("Failed to fetch CSRF token");
        }
        const data = await response.json();
        return String(data.csrf_token || "");
      })
      .catch((error) => {
        csrfTokenPromise = null;
        throw error;
      });
  }

  return csrfTokenPromise;
};

window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const requestUrl = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();

  if (!UNSAFE_METHODS.has(method) || !isSameOrigin(requestUrl)) {
    return originalFetch(input, init);
  }

  const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
  if (!headers.has("X-CSRF-Token")) {
    const token = await getCsrfToken();
    if (token) {
      headers.set("X-CSRF-Token", token);
    }
  }

  return originalFetch(input, {
    ...init,
    headers,
    credentials: init?.credentials || (input instanceof Request ? input.credentials : "same-origin")
  });
};

export {};
