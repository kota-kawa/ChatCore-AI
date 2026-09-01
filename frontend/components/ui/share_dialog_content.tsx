import type { ReactNode, RefObject } from "react";

import type { SocialShareLinks } from "../../lib/share";
import { CopyButton } from "./copy_button";

export type ShareDialogStatus = {
  text: string;
  isError: boolean;
};

export type ShareDialogContentProps = {
  shareUrl: string;
  shareLoading: boolean;
  shareStatus?: ShareDialogStatus | null;
  shareStatusId?: string;
  shareStatusClassName?: string;
  shareStatusErrorClassName?: string;
  bodyClassName?: string;

  linkInputId: string;
  linkInputAriaLabel?: string;
  linkPlaceholder: string;
  copyButtonId?: string;
  copyButtonRef?: RefObject<HTMLButtonElement | null>;
  copyLabel: string;
  copiedLabel?: string;
  onCopyLink: () => Promise<boolean> | boolean;

  socialLinks: SocialShareLinks;
  socialLinkIds?: {
    x?: string;
    line?: string;
    facebook?: string;
  };
  supportsNativeShare: boolean;
  nativeShareButtonId?: string;
  nativeShareLabel: string;
  onNativeShare: () => Promise<void> | void;
};

const X_LOGO_PATH =
  "M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z";

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

type ShareChannelLinkProps = {
  id?: string;
  href: string;
  title: string;
  disabled: boolean;
  children: ReactNode;
};

function ShareChannelLink({ id, href, title, disabled, children }: ShareChannelLinkProps) {
  return (
    <a
      id={id}
      className="cc-share-modal__channel"
      target="_blank"
      rel="noopener noreferrer"
      href={disabled ? undefined : href}
      title={title}
      aria-disabled={disabled ? "true" : undefined}
      tabIndex={disabled ? -1 : undefined}
      onClick={(event) => {
        if (disabled) event.preventDefault();
      }}
    >
      {children}
    </a>
  );
}

/** Shared URL/copy/social/native-share body used by chat, memo, and prompt modals. */
export function ShareDialogContent({
  shareUrl,
  shareLoading,
  shareStatus,
  shareStatusId,
  shareStatusClassName,
  shareStatusErrorClassName,
  bodyClassName,
  linkInputId,
  linkInputAriaLabel,
  linkPlaceholder,
  copyButtonId,
  copyButtonRef,
  copyLabel,
  copiedLabel,
  onCopyLink,
  socialLinks,
  socialLinkIds,
  supportsNativeShare,
  nativeShareButtonId,
  nativeShareLabel,
  onNativeShare,
}: ShareDialogContentProps) {
  const shareReady = Boolean(shareUrl.trim()) && !shareLoading;

  return (
    <div className={joinClassNames(bodyClassName, "cc-share-modal__body")}>
      <div className="cc-share-modal__field">
        <input
          type="text"
          id={linkInputId}
          readOnly
          placeholder={linkPlaceholder}
          aria-label={linkInputAriaLabel}
          value={shareUrl}
        />
        <CopyButton
          id={copyButtonId}
          buttonRef={copyButtonRef}
          onCopy={onCopyLink}
          label={copyLabel}
          copiedLabel={copiedLabel}
          className="cc-share-modal__copy"
          idleIcon="bi-files"
          disabled={!shareReady}
        />
      </div>

      {shareStatus ? (
        <p
          id={shareStatusId}
          className={joinClassNames(
            shareStatusClassName,
            shareStatus.isError ? shareStatusErrorClassName : undefined,
          )}
        >
          {shareStatus.text}
        </p>
      ) : null}

      <div className="cc-share-modal__channels">
        <ShareChannelLink
          id={socialLinkIds?.x}
          href={socialLinks.x}
          title="X"
          disabled={!shareReady || !socialLinks.x}
        >
          <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d={X_LOGO_PATH}></path>
          </svg>
          <span className="sr-only">X</span>
        </ShareChannelLink>
        <ShareChannelLink
          id={socialLinkIds?.line}
          href={socialLinks.line}
          title="LINE"
          disabled={!shareReady || !socialLinks.line}
        >
          <i className="bi bi-chat-dots" aria-hidden="true"></i>
          <span className="sr-only">LINE</span>
        </ShareChannelLink>
        <ShareChannelLink
          id={socialLinkIds?.facebook}
          href={socialLinks.facebook}
          title="Facebook"
          disabled={!shareReady || !socialLinks.facebook}
        >
          <i className="bi bi-facebook" aria-hidden="true"></i>
          <span className="sr-only">Facebook</span>
        </ShareChannelLink>

        {supportsNativeShare ? (
          <button
            type="button"
            id={nativeShareButtonId}
            className="cc-share-modal__channel"
            aria-label={nativeShareLabel}
            title={nativeShareLabel}
            disabled={!shareReady}
            onClick={() => {
              void onNativeShare();
            }}
          >
            <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
          </button>
        ) : null}
      </div>
    </div>
  );
}
