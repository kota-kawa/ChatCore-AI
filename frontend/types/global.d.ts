import type { DetailedHTMLProps, HTMLAttributes } from "react";

type HtmlTagProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>;
type DomPurifyConfig = {
  ALLOWED_TAGS?: string[];
  ALLOWED_ATTR?: string[];
};

type DomPurifyLike = {
  sanitize: (dirty: string, config?: DomPurifyConfig) => string;
};

declare global {
  const DOMPurify: DomPurifyLike;

  interface Window {
    DOMPurify: DomPurifyLike;
  }

  namespace JSX {
    interface IntrinsicElements {
      "action-menu": HtmlTagProps;
      "chat-action-menu": HtmlTagProps;
      "user-icon": HtmlTagProps;
    }
  }
}

export {};
