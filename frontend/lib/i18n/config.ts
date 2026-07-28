export const SUPPORTED_LOCALES = ["ja", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "ja";
export const LOCALE_COOKIE_NAME = "chatcore_locale";
export const LOCALE_STORAGE_KEY = "chatcore.locale";
export const LOCALE_CHANGE_EVENT = "chatcore:localechange";

export function isSupportedLocale(value: unknown): value is Locale {
  return typeof value === "string" && SUPPORTED_LOCALES.includes(value.toLowerCase().split("-")[0] as Locale);
}

export function normalizeLocale(value: unknown): Locale | null {
  if (typeof value !== "string") return null;
  const language = value.trim().toLowerCase().split(/[,_-]/)[0];
  return isSupportedLocale(language) ? language : null;
}

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

export function readLocaleCookie(cookieHeader: string | undefined): Locale | null {
  if (!cookieHeader) return null;
  for (const item of cookieHeader.split(";")) {
    const [name, ...valueParts] = item.trim().split("=");
    if (name === LOCALE_COOKIE_NAME) return normalizeLocale(decodeURIComponent(valueParts.join("=")));
  }
  return null;
}

export function resolveRequestLocale(cookieHeader?: string, acceptLanguage?: string | string[]): Locale {
  return readLocaleCookie(cookieHeader) ?? resolveAcceptLanguage(acceptLanguage) ?? DEFAULT_LOCALE;
}

export function getRuntimeLocale(): Locale {
  if (typeof document === "undefined") return DEFAULT_LOCALE;
  return normalizeLocale(document.documentElement.lang) ?? DEFAULT_LOCALE;
}
