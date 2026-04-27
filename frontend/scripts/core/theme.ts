export type ThemePreference = "light" | "dark" | "auto";

const STORAGE_KEY = "chatcore-theme";
const VALID_PREFERENCES: ThemePreference[] = ["light", "dark", "auto"];

function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (VALID_PREFERENCES as string[]).includes(value);
}

export function getStoredThemePreference(): ThemePreference {
  if (typeof window === "undefined") {
    return "auto";
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (isThemePreference(raw)) {
      return raw;
    }
  } catch {
    // localStorage unavailable
  }
  return "auto";
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
    if (preference === "auto") {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, preference);
    }
  } catch {
    // localStorage unavailable
  }
  applyTheme(resolveTheme(preference));
  notifyThemeChange(preference);
}

type ThemeChangeListener = (preference: ThemePreference) => void;
const themeChangeListeners = new Set<ThemeChangeListener>();

function notifyThemeChange(preference: ThemePreference): void {
  themeChangeListeners.forEach((listener) => {
    try {
      listener(preference);
    } catch (error) {
      console.error("theme change listener failed:", error);
    }
  });
}

export function onThemeChange(listener: ThemeChangeListener): () => void {
  themeChangeListeners.add(listener);
  return () => {
    themeChangeListeners.delete(listener);
  };
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
