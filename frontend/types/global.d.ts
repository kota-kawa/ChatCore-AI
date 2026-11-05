// カスタム要素（action-menu / chat-action-menu / user-icon）をJSXで使えるようにする型宣言。
// Type declarations that let the custom elements (action-menu, chat-action-menu, user-icon) be used in JSX.
import type { DetailedHTMLProps, HTMLAttributes } from "react";

type HtmlTagProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>;

// グローバルのJSX名前空間と、reactモジュール側のJSX名前空間の両方に同じ要素を登録する（どちらの参照方式でも型エラーにしないため）
// Register the same elements in both the global JSX namespace and the react module's JSX namespace so either lookup path type-checks
declare global {
  namespace JSX {
    interface IntrinsicElements {
      "action-menu": HtmlTagProps;
      "chat-action-menu": HtmlTagProps;
      "user-icon": HtmlTagProps;
    }
  }
}

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "action-menu": HtmlTagProps;
      "chat-action-menu": HtmlTagProps;
      "user-icon": HtmlTagProps;
    }
  }
}

export {};
