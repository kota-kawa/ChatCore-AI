type ToastVariant = "info" | "success" | "error";

type ToastOptions = {
  variant?: ToastVariant;
  durationMs?: number;
};

const TOAST_VIEWPORT_ID = "cc-toast-viewport";
const DEFAULT_DURATION_MS = 3600;

function ensureViewport() {
  let viewport = document.getElementById(TOAST_VIEWPORT_ID);
  if (viewport instanceof HTMLDivElement) {
    return viewport;
  }

  viewport = document.createElement("div");
  viewport.id = TOAST_VIEWPORT_ID;
  viewport.className = "cc-toast-viewport";
  viewport.setAttribute("role", "region");
  viewport.setAttribute("aria-live", "polite");
  viewport.setAttribute("aria-label", "通知");
  document.body.appendChild(viewport);
  return viewport;
}

function normalizeMessage(message?: unknown) {
  if (message === undefined || message === null) return "";
  return String(message).trim();
}

export function showToast(message?: unknown, options?: ToastOptions) {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  const text = normalizeMessage(message);
  if (!text) return;

  const viewport = ensureViewport();
  const toast = document.createElement("div");
  const variant: ToastVariant = options?.variant ?? "info";
  const durationMs = Math.max(1200, options?.durationMs ?? DEFAULT_DURATION_MS);

  toast.className = "cc-toast";
  toast.setAttribute("data-variant", variant);
  toast.setAttribute("role", variant === "error" ? "alert" : "status");
  toast.textContent = text;

  viewport.appendChild(toast);

  window.setTimeout(() => {
    toast.remove();
    if (!viewport.childElementCount) {
      viewport.remove();
    }
  }, durationMs);
}
