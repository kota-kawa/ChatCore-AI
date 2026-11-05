// 表示言語（ja / en）の定義と、Cookie・Accept-Language・URL・html の lang 属性から言語を決める関数群。
// Defines the supported display languages (ja / en) and the functions that resolve the locale from cookies, Accept-Language, the URL, and the html lang attribute.
// Used by pages/_app.tsx and the pages that resolve their locale on the server.

export const SUPPORTED_LOCALES = ["ja", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "ja";
export const LOCALE_COOKIE_NAME = "chatcore_locale";
export const LOCALE_STORAGE_KEY = "chatcore.locale";
export const LOCALE_CHANGE_EVENT = "chatcore:localechange";

// 対応言語かを判定する。"en-US" のような地域つきの指定は、言語部分だけで判定する。
// Checks whether a value is a supported locale; region-qualified tags such as "en-US" are judged by their language part.
export function isSupportedLocale(value: unknown): value is Locale {
  return typeof value === "string" && SUPPORTED_LOCALES.includes(value.toLowerCase().split("-")[0] as Locale);
}

// 任意の値を対応言語（ja / en）に正規化する。対応外や文字列以外は null。
// Normalizes an arbitrary value to a supported locale (ja / en); null for unsupported or non-string values.
export function normalizeLocale(value: unknown): Locale | null {
  if (typeof value !== "string") return null;
  const language = value.trim().toLowerCase().split(/[,_-]/)[0];
  return isSupportedLocale(language) ? language : null;
}

// Accept-Language ヘッダーを q 値の高い順（同じ値なら記載順）に並べ、最初に対応言語だったものを返す。
// Sorts the Accept-Language header by q value (header order on ties) and returns the first supported language.
export function resolveAcceptLanguage(header: string | string[] | undefined): Locale | null {
  const raw = Array.isArray(header) ? header.join(",") : header;
  if (!raw) return null;
  const candidates = raw.split(",").map((part, index) => {
    const [tag, ...parameters] = part.trim().split(";");
    const quality = parameters.reduce((current, parameter) => {
      const match = /^q=([0-9.]+)$/i.exec(parameter.trim());
      return match ? Number(match[1]) : current;
    }, 1);
    return { locale: normalizeLocale(tag), quality: Number.isFinite(quality) ? quality : 0, index };
  });
  candidates.sort((left, right) => right.quality - left.quality || left.index - right.index);
  return candidates.find((candidate) => candidate.locale)?.locale ?? null;
}

// Cookie ヘッダーから言語の Cookie だけを読み取る。
// Reads only the locale cookie from a Cookie header.
export function readLocaleCookie(cookieHeader: string | undefined): Locale | null {
  if (!cookieHeader) return null;
  for (const item of cookieHeader.split(";")) {
    const [name, ...valueParts] = item.trim().split("=");
    if (name === LOCALE_COOKIE_NAME) return normalizeLocale(decodeURIComponent(valueParts.join("=")));
  }
  return null;
}

// リクエストの言語を決める。優先順位は Cookie、Accept-Language、既定の日本語。
// Resolves the request's locale: cookie first, then Accept-Language, then the default (Japanese).
export function resolveRequestLocale(cookieHeader?: string, acceptLanguage?: string | string[]): Locale {
  return readLocaleCookie(cookieHeader) ?? resolveAcceptLanguage(acceptLanguage) ?? DEFAULT_LOCALE;
}

// URLで指定された言語を最優先し、ルート情報がない場合だけ従来の自動判定へ戻す。
// Prefer an explicit route locale and only fall back to the legacy request detection
// when routing information is unavailable.
export function resolvePageLocale(
  routeLocale?: string,
  cookieHeader?: string,
  acceptLanguage?: string | string[]
): Locale {
  return normalizeLocale(routeLocale) ?? resolveRequestLocale(cookieHeader, acceptLanguage);
}

// ブラウザ上で現在の言語を html の lang 属性から読む。サーバー側（document が無い環境）では既定の言語。
// Reads the current locale from the html lang attribute in the browser; returns the default locale on the server (no document).
export function getRuntimeLocale(): Locale {
  if (typeof document === "undefined") return DEFAULT_LOCALE;
  return normalizeLocale(document.documentElement.lang) ?? DEFAULT_LOCALE;
}
