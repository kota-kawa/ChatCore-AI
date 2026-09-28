export type ThemePreference = "light" | "dark" | "auto";

const STORAGE_KEY = "chatcore-theme";
const DEFAULT_THEME_PREFERENCE: ThemePreference = "light";
const VALID_PREFERENCES: ThemePreference[] = ["light", "dark", "auto"];
const THEME_NAME_PATTERN = /\b(theme|appearance|color scheme|colour scheme|dark mode|light mode)\b|テーマ|外観|配色|ダークモード|ライトモード/i;
const THEME_SETTING_REFERENCE_PATTERNS = [
  /\bcurrent(?:ly)?\s+(?:(?:color|colour)\s+)?(?:theme|appearance|color scheme|colour scheme|dark mode|light mode)\s+(?:setting|preference|configuration)\b|\b(?:currently selected|saved|configured|browser|app|application|site)\s+(?:(?:color|colour)\s+)?(?:theme|appearance|color scheme|colour scheme|dark mode|light mode)(?:\s+(?:setting|preference|configuration))?\b/i,
  /\bmy\s+(?:(?:current|saved|preferred)\s+)?(?:theme|appearance|color scheme|colour scheme|dark mode|light mode)\b(?!\s+(?:in|of|for)\s+(?:this|the|a)\s+(?:poem|story|book|essay|song|movie|film|novel|presentation|project))|\bmy\s+(?:(?:current|saved|preferred)\s+)?(?:theme|appearance|color scheme|colour scheme|dark mode|light mode)\s+(?:setting|preference|configuration)\b/i,
  /\b(?:theme|appearance|color scheme|colour scheme|dark mode|light mode)\s+(?:setting|preference|configuration|am I using|i(?:'m| am) using|is (?:enabled|active|selected)|do I have (?:set|selected))\b/i,
  /(?:今|現在)(?:の|の表示|の画面)?(?:テーマ|外観|配色|ダークモード|ライトモード)(?:設定|状態|は|を)|(?:テーマ|外観|配色|ダークモード|ライトモード)(?:の)?(?:設定|設定値|優先設定|状態)|(?:表示テーマ|画面テーマ|アプリテーマ|ブラウザーのテーマ|ブラウザのテーマ)/i,
];
const THEME_READ_REQUEST_PATTERN =
  /\b(?:what(?:'s| is)(?: my| the current)?|show(?: me)?|tell me|check|read|look up|find out|current(?:ly)?|list|summari[sz]e)\b|(?:今|現在|何|どの|教え|見せ|確認|調べ|知り|一覧|要約|まとめ|どうなって|設定は)|[?？]/i;
const THEME_WRITE_REQUEST_PATTERN =
  /\b(?:change|set|switch|make|turn|apply|choose|pick)\b.{0,24}\b(?:theme|appearance|color scheme|colour scheme|dark mode|light mode)\b|\b(?:theme|appearance|color scheme|colour scheme|dark mode|light mode)\b.{0,24}\b(?:to|as)\b.{0,10}\b(?:dark|light|auto)\b|(?:テーマ|配色|外観).{0,16}(?:変更|変え|切替|切り替え|にして|にする|に設定|を設定|更新|適用|選択して|選んで)/i;

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

export function shouldSendThemePreference(message: string): boolean {
  return (
    THEME_NAME_PATTERN.test(message) &&
    THEME_SETTING_REFERENCE_PATTERNS.some((pattern) => pattern.test(message)) &&
    THEME_READ_REQUEST_PATTERN.test(message) &&
    !THEME_WRITE_REQUEST_PATTERN.test(message)
  );
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
