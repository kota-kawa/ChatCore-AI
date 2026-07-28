import type { MessageKey } from "../i18n/catalogs/ja";
import type { Locale } from "../i18n/config";
import type { ModelOption } from "./types";

// モデル名は固有名詞なので翻訳せず、用途の補足だけをロケールに合わせて括弧書きする
// The model name is a proper noun, so only the usage hint is translated and parenthesized per locale
export function formatModelOptionLabel(
  option: ModelOption,
  t: (key: MessageKey) => string,
  locale: Locale
): string {
  const description = t(option.descriptionKey);
  return locale === "en" ? `${option.label} (${description})` : `${option.label}（${description}）`;
}
