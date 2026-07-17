export type ThemePreference = "light" | "dark" | "auto";

const STORAGE_KEY = "chatcore-theme";
const DEFAULT_THEME_PREFERENCE: ThemePreference = "light";
const VALID_PREFERENCES: ThemePreference[] = ["light", "dark", "auto"];

function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (VALID_PREFERENCES as string[]).includes(value);
}

export function getStoredThemePreference(): ThemePreference {
  if (typeof window === "undefined") {
    return DEFAULT_THEME_PREFERENCE;
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (isThemePreference(raw)) {
      return raw;
    }
  } catch {
    // localStorage unavailable
  }
  return DEFAULT_THEME_PREFERENCE;
}

export function resolveTheme(preference: ThemePreference): "light" | "dark" {
  if (preference === "light" || preference === "dark") {
    return preference;
  }
  if (typeof window === "undefined" || !window.matchMedia) {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: "light" | "dark"): void {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.setAttribute("data-theme", theme);
}

export function setThemePreference(preference: ThemePreference): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    // localStorage unavailable
  }
  applyTheme(resolveTheme(preference));
}

let systemMediaQuery: MediaQueryList | null = null;
let systemListenerAttached = false;

export function watchSystemTheme(): void {
  if (typeof window === "undefined" || !window.matchMedia) {
    return;
  }
  if (systemListenerAttached) {
    return;
  }
  systemMediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const handler = () => {
    if (getStoredThemePreference() === "auto") {
      applyTheme(resolveTheme("auto"));
    }
  };
  if (typeof systemMediaQuery.addEventListener === "function") {
    systemMediaQuery.addEventListener("change", handler);
  } else if (typeof systemMediaQuery.addListener === "function") {
    systemMediaQuery.addListener(handler);
  }
  systemListenerAttached = true;
}
