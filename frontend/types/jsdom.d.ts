// jsdom は型定義を同梱しないため、本プロジェクトで使用する最小限のAPIのみを宣言する。
// （@types/jsdom の追加依存を避けるための narrow なアンビエント宣言）
// jsdom ships no type definitions, so declare only the minimal API surface this project uses.
// (A narrow ambient declaration to avoid adding the @types/jsdom dependency.)
declare module "jsdom" {
  import type { WindowLike } from "dompurify";

  // DOMPurify初期化とdocument取得に必要なwindowの最小型
  // Minimal window type needed for DOMPurify initialization and document access
  type JsdomWindow = WindowLike & { document: Document; close(): void };

  type JsdomOptions = {
    pretendToBeVisual?: boolean;
    runScripts?: "dangerously" | "outside-only";
  };

  class JSDOM {
    constructor(html?: string, options?: JsdomOptions);
    readonly window: JsdomWindow;
  }

  export { JSDOM };
}
