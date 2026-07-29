import { enMessages } from "./catalogs/en";
import { jaMessages, type MessageKey } from "./catalogs/ja";
import type { Locale } from "./config";

// React に依存しない翻訳の実体。React ツリーの外で動く Web Components
// （user-icon など）からもカタログを参照できるように、Provider から分離している。
// The translation primitives, free of any React dependency, so Web Components that live
// outside the React tree (user-icon and friends) can read the same catalogues.

export type TranslationValues = Record<string, string | number>;

const catalogs = { ja: jaMessages, en: enMessages } as const;

export function interpolate(message: string, values?: TranslationValues) {
  if (!values) return message;
  return message.replace(/\{(\w+)\}/g, (match, name: string) => String(values[name] ?? match));
}

export function translate(locale: Locale, key: MessageKey, values?: TranslationValues) {
  return interpolate(catalogs[locale][key] ?? jaMessages[key], values);
}
