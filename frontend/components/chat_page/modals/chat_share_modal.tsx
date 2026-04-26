import { useEffect, useRef } from "react";

import type { ShareStatus } from "../../../lib/chat_page/types";

type ChatShareModalProps = {
  shareModalOpen: boolean;
  shareStatus: ShareStatus;
  shareUrl: string;
  shareLoading: boolean;
  supportsNativeShare: boolean;
  shareXUrl: string;
  shareLineUrl: string;
  shareFacebookUrl: string;
  closeShareModal: () => void;
  copyShareLink: () => void;
  shareWithNativeSheet: () => void;
};

export function ChatShareModal({
  shareModalOpen,
  shareStatus,
  shareUrl,
  shareLoading,
  supportsNativeShare,
  shareXUrl,
  shareLineUrl,
  shareFacebookUrl,
  closeShareModal,
  copyShareLink,
  shareWithNativeSheet,
}: ChatShareModalProps) {
  const modalRef = useRef<HTMLDivElement | null>(null);
  const previousFocusedElementRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!shareModalOpen) return;

    previousFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    window.requestAnimationFrame(() => {
      modalRef.current?.querySelector<HTMLElement>("#chat-share-copy-btn")?.focus();
    });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const modal = modalRef.current;
      if (!modal) return;

      const focusable = Array.from(
        modal.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute("hidden"));

      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement as HTMLElement | null;

      if (event.shiftKey && activeElement === first) {
        event.preventDefault();
        last.focus();
        return;
      }
      if (!event.shiftKey && activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previousFocusedElementRef.current?.isConnected) {
        previousFocusedElementRef.current.focus();
      }
      previousFocusedElementRef.current = null;
    };
  }, [shareModalOpen]);

  return (
    <div
      ref={modalRef}
      id="chat-share-modal"
      className={`chat-share-modal modal-base ${shareModalOpen ? "is-open" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-hidden={shareModalOpen ? "false" : "true"}
      aria-labelledby="chat-share-title"
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          closeShareModal();
        }
      }}
    >
      <div className="chat-share-modal__content">
        <div className="chat-share-modal__header">
          <h5 id="chat-share-title">チャットを共有</h5>
          <button
            type="button"
            id="chat-share-close-btn"
            className="chat-share-close-btn"
            aria-label="共有モーダルを閉じる"
            onClick={closeShareModal}
          >
            <i className="bi bi-x-lg"></i>
          </button>
        </div>

        <p className="chat-share-modal__desc">
          共有リンクを作成すると、このチャットルームの履歴をURL経由で閲覧できます。
        </p>

        <div className="chat-share-link-row">
          <input
            type="text"
            id="chat-share-link-input"
            readOnly
            placeholder="共有リンクを準備しています"
            value={shareUrl}
          />
        </div>

        <p id="chat-share-status" className={`chat-share-status ${shareStatus.error ? "chat-share-status--error" : ""}`.trim()}>
          {shareStatus.message}
        </p>

        <div className="chat-share-actions">
          <button
            type="button"
            id="chat-share-copy-btn"
            className="primary-button chat-share-icon-btn"
            aria-label="リンクをコピー"
            title="リンクをコピー"
            disabled={shareLoading}
            onClick={copyShareLink}
          >
            <i className="bi bi-files" aria-hidden="true"></i>
          </button>
          <button
            type="button"
            id="chat-share-web-btn"
            className="primary-button chat-share-icon-btn"
            aria-label="端末で共有"
            title="端末で共有"
            disabled={shareLoading}
            onClick={shareWithNativeSheet}
            hidden={!supportsNativeShare}
          >
            <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
          </button>
        </div>

        <div className="chat-share-sns">
          <a id="chat-share-sns-x" target="_blank" rel="noopener noreferrer" href={shareXUrl}>
            <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
              ></path>
            </svg>
            <span>X</span>
          </a>
          <a id="chat-share-sns-line" target="_blank" rel="noopener noreferrer" href={shareLineUrl}>
            <i className="bi bi-chat-dots"></i>
            <span>LINE</span>
          </a>
          <a
            id="chat-share-sns-facebook"
            target="_blank"
            rel="noopener noreferrer"
            href={shareFacebookUrl}
          >
            <i className="bi bi-facebook"></i>
            <span>Facebook</span>
          </a>
        </div>
      </div>
    </div>
  );
}
