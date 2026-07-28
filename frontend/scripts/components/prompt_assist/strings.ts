import { getRuntimeLocale } from "../../../lib/i18n/config";

// このパネルは React 外のバニラJSなので、scripts/core/passkeys.ts と同じく
// <html lang> から実行時ロケールを読んで文言を切り替える
// This panel lives outside React, so it reads the runtime locale from <html lang>
// the same way scripts/core/passkeys.ts does
export function localized(ja: string, en: string): string {
  return getRuntimeLocale() === "en" ? en : ja;
}
