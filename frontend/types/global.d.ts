import type { DetailedHTMLProps, HTMLAttributes } from "react";

type HtmlTagProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>;

declare global {
  const DOMPurify: {
    sanitize: (
      dirty: string,
      config?: {
        ALLOWED_TAGS?: string[];
        ALLOWED_ATTR?: string[];
      }
    ) => string;
  };

  const bootstrap: {
    Modal: {
      new (element: Element): { show: () => void; hide: () => void };
      getInstance: (element: Element | null) => { show: () => void; hide: () => void } | null;
    };
  };

  namespace JSX {
    interface IntrinsicElements {
      "action-menu": HtmlTagProps;
      "chat-action-menu": HtmlTagProps;
      "user-icon": HtmlTagProps;
    }
  }
}

export {};
