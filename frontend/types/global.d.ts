import type { DetailedHTMLProps, HTMLAttributes } from "react";

type HtmlTagProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>;

declare global {
  namespace JSX {
    interface IntrinsicElements {
      "action-menu": HtmlTagProps;
      "chat-action-menu": HtmlTagProps;
      "user-icon": HtmlTagProps;
    }
  }
}

export {};
