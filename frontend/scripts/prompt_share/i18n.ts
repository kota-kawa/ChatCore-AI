import { enMessages } from "../../lib/i18n/catalogs/en";
import { jaMessages, type MessageKey } from "../../lib/i18n/catalogs/ja";
import { normalizeLocale, type Locale } from "../../lib/i18n/config";

export type PromptShareMessageKey = Extract<MessageKey, `promptShare.${string}`>;
type Values = Record<string, string | number>;

export function getPromptShareLocale(): Locale {
  if (typeof document === "undefined") return "ja";
  return normalizeLocale(document.documentElement.lang) ?? "ja";
}

export function promptShareText(
  key: PromptShareMessageKey,
  values?: Values,
  locale: Locale = getPromptShareLocale()
): string {
  const catalog = locale === "en" ? enMessages : jaMessages;
  const message = catalog[key] ?? jaMessages[key];
  if (!values) return message;
  return message.replace(/\{(\w+)\}/g, (match, name: string) => String(values[name] ?? match));
}
