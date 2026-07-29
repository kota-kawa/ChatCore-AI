import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
  // この文書が実際に描画されているロケール。bfcache復元時に永続化済みの値と比べ、
  // 同一文書内での切り替え（再読み込み不要）と、別文書での切り替えを区別する。
  // The locale this document is actually rendered in. Compared against the persisted
  // value on bfcache restore to tell an in-document switch (no reload needed) apart
  // from one made in another document.
  const renderedLocaleRef = useRef<Locale>(initialLocale);
  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
    persistLocale(nextLocale);
  }, []);

  useEffect(() => {
    renderedLocaleRef.current = locale;
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
    // 設定画面への遷移はプレーンな<a>リンクによるフルページ遷移のため、言語変更後に
    // 戻ると、ブラウザは旧言語のページをbfcacheからそのまま復元する。ここでReactの
    // stateだけを新しい言語へ差し替えると、SSR済みHTML・バニラJSが構築したDOM・
    // 取得済みAPIデータ（SWRキャッシュ）は旧言語のまま残るため、言語が混在して
    // レイアウトが崩れる。ページ全体を再読み込みして一貫した状態へ戻すことで、
    // 利用者が手動で再読込しなくても新しい言語が正しく反映される。
    // Settings is reached by a full page load, so after a language change the browser
    // restores the previous page from bfcache still in the old language. Swapping only
    // the React state would leave the SSR'd HTML, vanilla-rendered DOM, and already
    // fetched API data (SWR cache) in the old language — a mixed-language page with a
    // broken layout. Reload instead so the page comes back fully consistent, without
    // the user having to reload by hand.
    const onPageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return;
      const persisted = readPersistedLocale();
      if (!persisted || persisted === renderedLocaleRef.current) return;
      window.location.reload();
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
