import type { DetailedHTMLProps, HTMLAttributes } from "react";

type HtmlTagProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>;
type DomPurifyConfig = {
  ALLOWED_TAGS?: string[];
  ALLOWED_ATTR?: string[];
};

type DomPurifyLike = {
  sanitize: (dirty: string, config?: DomPurifyConfig) => string;
};

type BootstrapModalInstance = {
  show: () => void;
  hide: () => void;
};

type BootstrapLike = {
  Modal: {
    new (element: Element): BootstrapModalInstance;
    getInstance: (element: Element | null) => BootstrapModalInstance | null;
  };
};

declare global {
  const DOMPurify: DomPurifyLike;
  const bootstrap: BootstrapLike;

  interface Window {
    DOMPurify: DomPurifyLike;
    bootstrap: BootstrapLike;
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
