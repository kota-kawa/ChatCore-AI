// 表示言語（ja / en）を保持して全コンポーネントへ配る Context。言語の保存（Cookie と localStorage）、切り替え演出、他タブ・bfcache 復元時の追従を担う。
// Context holding the display language (ja / en) for all components; handles persisting it (cookie and localStorage), the switch transition, and following changes from other tabs and bfcache restores.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { jaMessages, type MessageKey } from "../lib/i18n/catalogs/ja";
import {
  DEFAULT_LOCALE, LOCALE_CHANGE_EVENT, LOCALE_COOKIE_NAME, LOCALE_STORAGE_KEY,
  normalizeLocale, readLocaleCookie, type Locale
} from "../lib/i18n/config";
import { finishBootLocaleTransition, reloadWithLocaleTransition, runLocaleTransition } from "../lib/i18n/locale_transition";
import { interpolate, translate, type TranslationValues } from "../lib/i18n/translate";

type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, values?: TranslationValues) => string;
  formatDate: (value: Date | number | string, options?: Intl.DateTimeFormatOptions) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
};

// Provider の外では null になる。その場合は useTranslation が日本語の fallbackContext を返す
// Null outside a provider; useTranslation then returns the Japanese fallbackContext
const LocaleContext = createContext<LocaleContextValue | null>(null);

// setLocale直後にawaitを挟んで表示するメッセージは、React再レンダリング前のためcontextの`t`が
// 旧ロケールのクロージャのままになる。呼び出し側が対象ロケールを明示できるよう再公開する。
// Messages shown right after setLocale (past an await) can't rely on context `t` — that closure
// still reflects the pre-render locale. Re-exported so those call sites can name the locale.
export { translate };

// 選んだ言語を Cookie（サーバー描画用）と localStorage（他タブへの通知用）に保存する
// Persist the chosen language to a cookie (read for server rendering) and to localStorage (which notifies other tabs)
function persistLocale(locale: Locale) {
  if (typeof document === "undefined") return;
  document.cookie = `${LOCALE_COOKIE_NAME}=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`;
  try { window.localStorage.setItem(LOCALE_STORAGE_KEY, locale); } catch { /* ブラウザー保存領域が利用できない場合もある。
    storage can be unavailable */ }
}

// 保存済みの言語を読む。Cookie を優先し、無ければ localStorage を使う
// Read the persisted language, preferring the cookie and falling back to localStorage
function readPersistedLocale(): Locale | null {
  if (typeof document === "undefined") return null;
  const fromCookie = readLocaleCookie(document.cookie);
  if (fromCookie) return fromCookie;
  try { return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY)); } catch { return null; }
}

// Provider なしで描画された場合（SSR 補助・テスト）に使う日本語固定の既定値
// Japanese-only default used when rendered without a provider (SSR helpers, tests)
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

// 言語の状態を持ち、<html> の lang 属性の更新、他タブからの変更の反映、bfcache 復元時の再読み込みを行う
// Owns the language state, keeps the <html> lang attribute updated, applies changes from other tabs, and reloads on a bfcache restore
export function LocaleProvider({ initialLocale = DEFAULT_LOCALE, children }: { initialLocale?: Locale; children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  // この文書が実際に描画されているロケール。bfcache復元時に永続化済みの値と比べ、
  // 同一文書内での切り替え（再読み込み不要）と、別文書での切り替えを区別する。
  // The locale this document is actually rendered in. Compared against the persisted
  // value on bfcache restore to tell an in-document switch (no reload needed) apart
  // from one made in another document.
  const renderedLocaleRef = useRef<Locale>(initialLocale);
  const setLocale = useCallback((nextLocale: Locale) => {
    persistLocale(nextLocale);
    // 実際に表示が変わるときだけ演出する。設定画面は初期化時にも保存済みの言語で
    // setLocale を呼ぶため、同じ言語での呼び出しまで演出すると無意味に画面が
    // ちらついてしまう。
    // Animate only when the visible language actually changes. The settings page also
    // calls setLocale with the already-active language while initializing, and animating
    // that would flicker the screen for no reason.
    if (nextLocale === renderedLocaleRef.current) return;
    runLocaleTransition(() => setLocaleState(nextLocale));
  }, []);

  useEffect(() => {
    renderedLocaleRef.current = locale;
    document.documentElement.lang = locale;
    document.documentElement.setAttribute("data-locale", locale);
    window.dispatchEvent(new CustomEvent(LOCALE_CHANGE_EVENT, { detail: { locale } }));
  }, [locale]);

  useEffect(() => {
    // 別タブで言語が変わったとき（localStorage の更新）に、このタブの表示も合わせる
    // Follow a language change made in another tab (a localStorage update)
    const onStorage = (event: StorageEvent) => {
      if (event.key !== LOCALE_STORAGE_KEY) return;
      const nextLocale = normalizeLocale(event.newValue);
      if (!nextLocale || nextLocale === renderedLocaleRef.current) return;
      runLocaleTransition(() => setLocaleState(nextLocale));
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    // 言語変更による再読み込み直後は、描画前にフェードインの初期状態が当たっている。
    // アニメーション終了後に演出用の属性を取り除く。
    // Right after a language-change reload the fade-in starting state is already applied
    // before paint; drop the transition attribute once the animation has finished.
    finishBootLocaleTransition();
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
      reloadWithLocaleTransition();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  const value = useMemo<LocaleContextValue>(() => ({
    locale,
    setLocale,
    t: (key, values) => translate(locale, key, values),
    formatDate: (input, options) => {
      const date = input instanceof Date ? input : new Date(input);
      return new Intl.DateTimeFormat(locale === "ja" ? "ja-JP" : "en-US", options).format(date);
    },
    formatNumber: (input, options) => new Intl.NumberFormat(locale === "ja" ? "ja-JP" : "en-US", options).format(input)
  }), [locale, setLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

// 翻訳関数 t、現在の言語、日付・数値の整形関数を返す hook
// Hook returning the translate function t, the current locale, and date / number formatters
export function useTranslation() {
  const context = useContext(LocaleContext);
  // SSR補助処理や単体テストではProvider外で描画するため、日本語の既定値を保つ。
  // Components are also rendered in isolation by SSR helpers and tests. Keep a
  // Japanese fallback so incremental catalogue adoption never crashes a page.
  return context ?? fallbackContext;
}
