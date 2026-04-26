import { useCallback, useRef } from "react";

import { useModalFocusTrap } from "../../../hooks/use_modal_focus_trap";
import type { ShareStatus } from "../../../lib/chat_page/types";
import { ModalCloseButton } from "../../ui/modal_close_button";

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
  const getInitialFocus = useCallback(() => {
    return modalRef.current?.querySelector<HTMLElement>("#chat-share-copy-btn") ?? null;
  }, []);

  useModalFocusTrap({
    isOpen: shareModalOpen,
    containerRef: modalRef,
    getInitialFocus,
    onEscape: closeShareModal,
  });

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
          <ModalCloseButton
            id="chat-share-close-btn"
            className="chat-share-close-btn"
            label="共有モーダルを閉じる"
            onClick={closeShareModal}
          />
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
