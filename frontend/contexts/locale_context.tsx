import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { enMessages } from "../lib/i18n/catalogs/en";
import { jaMessages, type MessageKey } from "../lib/i18n/catalogs/ja";
import {
  DEFAULT_LOCALE, LOCALE_CHANGE_EVENT, LOCALE_COOKIE_NAME, LOCALE_STORAGE_KEY,
  normalizeLocale, readLocaleCookie, type Locale
} from "../lib/i18n/config";

type TranslationValues = Record<string, string | number>;
type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, values?: TranslationValues) => string;
  formatDate: (value: Date | number | string, options?: Intl.DateTimeFormatOptions) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
};

const catalogs = { ja: jaMessages, en: enMessages } as const;
const LocaleContext = createContext<LocaleContextValue | null>(null);

function interpolate(message: string, values?: TranslationValues) {
  if (!values) return message;
  return message.replace(/\{(\w+)\}/g, (match, name: string) => String(values[name] ?? match));
}

// setLocale直後にawaitを挟んで表示するメッセージは、React再レンダリング前のためcontextの`t`が
// 旧ロケールのクロージャのままになる。呼び出し側が対象ロケールを明示できるよう公開する。
// Messages shown right after setLocale (past an await) can't rely on context `t` — that closure
// still reflects the pre-render locale. Expose a locale-explicit translator for those call sites.
export function translate(locale: Locale, key: MessageKey, values?: TranslationValues) {
  return interpolate(catalogs[locale][key] ?? jaMessages[key], values);
}

function persistLocale(locale: Locale) {
  if (typeof document === "undefined") return;
  document.cookie = `${LOCALE_COOKIE_NAME}=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`;
  try { window.localStorage.setItem(LOCALE_STORAGE_KEY, locale); } catch { /* storage can be unavailable */ }
}

function readPersistedLocale(): Locale | null {
  if (typeof document === "undefined") return null;
  const fromCookie = readLocaleCookie(document.cookie);
  if (fromCookie) return fromCookie;
  try { return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY)); } catch { return null; }
}

const fallbackContext: LocaleContextValue = {
  locale: DEFAULT_LOCALE,
  setLocale: () => undefined,
  t: (key, values) => interpolate(jaMessages[key], values),
  formatDate: (input, options) => {
    const date = input instanceof Date ? input : new Date(input);
    return new Intl.DateTimeFormat("ja-JP", options).format(date);
  },
  formatNumber: (input, options) => new Intl.NumberFormat("ja-JP", options).format(input)
};

export function LocaleProvider({ initialLocale = DEFAULT_LOCALE, children }: { initialLocale?: Locale; children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
    persistLocale(nextLocale);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.setAttribute("data-locale", locale);
    window.dispatchEvent(new CustomEvent(LOCALE_CHANGE_EVENT, { detail: { locale } }));
  }, [locale]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== LOCALE_STORAGE_KEY) return;
      const nextLocale = normalizeLocale(event.newValue);
      if (nextLocale) setLocaleState(nextLocale);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    // 設定画面への遷移はプレーンな<a>リンクによるフルページ遷移のため、ブラウザの
    // bfcacheから元ページが復元されると、そのページのJSは実行されず旧ロケールの
    // まま表示され続ける。bfcache復元時（pageshowのpersisted）に永続化済みの値へ
    // 再同期し、リロードなしで正しい言語を反映する。
    // Navigating to Settings is a full-page load via a plain <a> link, so when the
    // browser restores the previous page from bfcache, its JS doesn't re-run and it
    // keeps showing the old locale. Resync from the persisted value on bfcache
    // restore (pageshow's persisted flag) so the correct language shows without a reload.
    const onPageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return;
      const persisted = readPersistedLocale();
      if (persisted) setLocaleState((current) => (current === persisted ? current : persisted));
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  const value = useMemo<LocaleContextValue>(() => ({
    locale,
    setLocale,
    t: (key, values) => interpolate(catalogs[locale][key] ?? jaMessages[key], values),
    formatDate: (input, options) => {
      const date = input instanceof Date ? input : new Date(input);
      return new Intl.DateTimeFormat(locale === "ja" ? "ja-JP" : "en-US", options).format(date);
    },
    formatNumber: (input, options) => new Intl.NumberFormat(locale === "ja" ? "ja-JP" : "en-US", options).format(input)
  }), [locale, setLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useTranslation() {
  const context = useContext(LocaleContext);
  // Components are also rendered in isolation by SSR helpers and tests. Keep a
  // Japanese fallback so incremental catalogue adoption never crashes a page.
  return context ?? fallbackContext;
}
