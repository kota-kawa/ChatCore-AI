import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { enMessages } from "../lib/i18n/catalogs/en";
import { jaMessages, type MessageKey } from "../lib/i18n/catalogs/ja";
import {
  DEFAULT_LOCALE, LOCALE_CHANGE_EVENT, LOCALE_COOKIE_NAME, LOCALE_STORAGE_KEY,
  normalizeLocale, type Locale
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

function persistLocale(locale: Locale) {
  if (typeof document === "undefined") return;
  document.cookie = `${LOCALE_COOKIE_NAME}=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`;
  try { window.localStorage.setItem(LOCALE_STORAGE_KEY, locale); } catch { /* storage can be unavailable */ }
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
